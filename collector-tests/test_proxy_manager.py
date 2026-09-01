import threading
import time

import pytest

from collector.utils.proxies import (
    ProxyConfigurationError,
    ProxyManager,
    ProxyManagerClosed,
    load_proxy_file,
    parse_proxy_line,
    redact_url,
)


def endpoint(index: int):
    return parse_proxy_line(
        f"proxy{index}.example:800{index}:user{index}:secret{index}",
        label=f"proxy-{index:03d}",
    )


def manager(
    count=2,
    *,
    global_concurrency=2,
    per_proxy_concurrency=1,
    failure_threshold=2,
    cooldown=0.05,
    allow_direct=False,
    rpm=1_000_000,
):
    return ProxyManager(
        [endpoint(index) for index in range(1, count + 1)],
        global_concurrency=global_concurrency,
        global_requests_per_minute=rpm,
        requests_per_minute_per_proxy=rpm,
        concurrent_requests_per_proxy=per_proxy_concurrency,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown,
        allow_direct_fallback=allow_direct,
    )


def test_parses_provider_format_and_authenticated_url_without_repr_leak() -> None:
    proxy = parse_proxy_line(
        "proxy.example:8080:driver:p@ss:word",
        label="proxy-001",
    )

    assert proxy.host == "proxy.example"
    assert proxy.port == 8080
    assert proxy.proxy_auth == ("driver", "p@ss:word")
    assert "p%40ss%3Aword" in proxy.authenticated_url
    assert "driver" not in repr(proxy)
    assert "p@ss" not in repr(proxy)


def test_parses_url_with_and_without_authentication() -> None:
    authenticated = parse_proxy_line(
        "http://driver:p%40ss@proxy.example:8080",
        label="proxy-001",
    )
    anonymous = parse_proxy_line(
        "https://proxy.example:8443",
        label="proxy-002",
    )

    assert authenticated.proxy_auth == ("driver", "p@ss")
    assert anonymous.proxy_auth == ("", "")
    assert anonymous.base_url == "https://proxy.example:8443"


def test_loads_comments_and_rejects_empty_invalid_or_duplicate_files(tmp_path) -> None:
    valid = tmp_path / "proxies"
    valid.write_text(
        "# authorized\nproxy1.example:8001:user:pass\n\n"
        "proxy2.example:8002:user:pass\n",
        encoding="utf-8",
    )
    assert [proxy.label for proxy in load_proxy_file(valid)] == [
        "proxy-001",
        "proxy-002",
    ]

    empty = tmp_path / "empty"
    empty.write_text("# no proxies\n", encoding="utf-8")
    with pytest.raises(ProxyConfigurationError, match="no entries"):
        load_proxy_file(empty)

    invalid = tmp_path / "invalid"
    invalid.write_text("not-a-proxy\n", encoding="utf-8")
    with pytest.raises(ProxyConfigurationError):
        load_proxy_file(invalid)

    duplicate = tmp_path / "duplicate"
    duplicate.write_text(
        "proxy.example:8080:user:one\nproxy.example:8080:user:two\n",
        encoding="utf-8",
    )
    with pytest.raises(ProxyConfigurationError, match="duplicate"):
        load_proxy_file(duplicate)


def test_round_robin_distributes_requests() -> None:
    proxy_manager = manager(count=3)
    labels = []
    for _ in range(6):
        with proxy_manager.acquire() as lease:
            labels.append(lease.label)
            proxy_manager.report(lease, latency=0.1, status_code=200)

    assert labels == [
        "proxy-001",
        "proxy-002",
        "proxy-003",
        "proxy-001",
        "proxy-002",
        "proxy-003",
    ]


def test_global_and_per_proxy_concurrency_are_bounded() -> None:
    proxy_manager = manager(count=2, global_concurrency=2)
    first = proxy_manager.acquire()
    second = proxy_manager.acquire()
    acquired = threading.Event()

    def acquire_third() -> None:
        with proxy_manager.acquire():
            acquired.set()

    thread = threading.Thread(target=acquire_third)
    thread.start()
    assert not acquired.wait(0.02)

    first.release()
    assert acquired.wait(0.2)
    second.release()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_global_rate_is_evenly_paced() -> None:
    proxy_manager = manager(count=2, rpm=6_000)
    started = time.monotonic()
    with proxy_manager.acquire():
        pass
    with proxy_manager.acquire():
        pass

    assert time.monotonic() - started >= 0.009


def test_direct_mode_uses_global_rate_instead_of_per_proxy_rate() -> None:
    proxy_manager = ProxyManager(
        [],
        global_concurrency=2,
        global_requests_per_minute=6_000,
        requests_per_minute_per_proxy=60,
        concurrent_requests_per_proxy=1,
        failure_threshold=2,
        cooldown_seconds=0.05,
        allow_direct_fallback=True,
    )
    started = time.monotonic()
    with proxy_manager.acquire():
        pass
    with proxy_manager.acquire():
        pass

    assert 0.009 <= time.monotonic() - started < 0.2


def test_429_reduces_concurrency_and_uses_another_proxy_after_backoff() -> None:
    proxy_manager = manager(count=2, global_concurrency=4, cooldown=0.03)
    with proxy_manager.acquire() as lease:
        assert lease.label == "proxy-001"
        proxy_manager.report(lease, latency=0.1, status_code=429)

    snapshot = proxy_manager.snapshot()
    assert snapshot["effective_concurrency"] == 2
    assert snapshot["proxies"][0]["rate_limited"] == 1
    assert snapshot["proxies"][0]["in_cooldown"] is True

    with proxy_manager.acquire() as lease:
        assert lease.label == "proxy-002"


def test_407_is_an_authentication_failure_and_immediately_cools_proxy() -> None:
    proxy_manager = manager(count=1, cooldown=0.05)
    with proxy_manager.acquire() as lease:
        proxy_manager.report(lease, latency=0.1, status_code=407)

    proxy = proxy_manager.snapshot()["proxies"][0]
    assert proxy["successes"] == 0
    assert proxy["errors"] == 1
    assert proxy["authentication_failures"] == 1
    assert proxy["in_cooldown"] is True


def test_repeated_failures_cause_cooldown_and_proxy_recovers() -> None:
    proxy_manager = manager(count=1, cooldown=0.02)
    for _ in range(2):
        with proxy_manager.acquire() as lease:
            proxy_manager.report(
                lease,
                latency=0.1,
                status_code="connection_error",
            )

    assert proxy_manager.snapshot()["proxies"][0]["in_cooldown"] is True
    time.sleep(0.025)
    with proxy_manager.acquire() as lease:
        assert lease.label == "proxy-001"


def test_direct_fallback_only_when_every_proxy_is_in_cooldown() -> None:
    proxy_manager = manager(count=1, cooldown=0.05, allow_direct=True)
    with proxy_manager.acquire() as lease:
        proxy_manager.report(lease, latency=0.1, status_code=403)

    with proxy_manager.acquire() as lease:
        assert lease.label == "direct"
        assert lease.endpoint is None


def test_close_unblocks_pending_acquisitions_without_losing_owner() -> None:
    proxy_manager = manager(count=1)
    owned = proxy_manager.acquire()
    closed = threading.Event()

    def wait_for_proxy() -> None:
        with pytest.raises(ProxyManagerClosed):
            proxy_manager.acquire()
        closed.set()

    thread = threading.Thread(target=wait_for_proxy)
    thread.start()
    assert not closed.wait(0.02)
    proxy_manager.close()
    assert closed.wait(0.2)
    owned.release()
    thread.join(timeout=1)


def test_log_url_redaction_removes_credentials_and_query_tokens() -> None:
    safe = redact_url(
        "https://driver:secret@example.test/path?token=top-secret#fragment"
    )
    assert safe == "https://example.test/path"
    assert "driver" not in safe
    assert "secret" not in safe
