import logging
import threading

import pytest
import requests

import collector.utils.http_scrapper as http_module
from collector.utils.http_scrapper import HttpScrapper, RetryError
from collector.utils.proxies import ProxyManager, parse_proxy_line


class FakeResponse:
    def __init__(self, status_code, *, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {"ok": True}

    def json(self):
        return self._payload


class SequenceSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.trust_env = True

    def request(self, **kwargs):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        pass


def build_manager(count=2, cooldown=0.001):
    proxies = [
        parse_proxy_line(
            f"proxy{index}.example:800{index}:user:secret{index}",
            label=f"proxy-{index:03d}",
        )
        for index in range(1, count + 1)
    ]
    return ProxyManager(
        proxies,
        global_concurrency=2,
        global_requests_per_minute=1_000_000,
        requests_per_minute_per_proxy=1_000_000,
        concurrent_requests_per_proxy=1,
        failure_threshold=2,
        cooldown_seconds=cooldown,
        allow_direct_fallback=False,
    )


def test_429_moves_proxy_to_cooldown_and_retries_on_another_proxy(
    monkeypatch,
) -> None:
    manager = build_manager(2)
    scraper = HttpScrapper(proxy_manager=manager)
    session = SequenceSession(
        [FakeResponse(429, headers={"Retry-After": "0"}), FakeResponse(200)]
    )
    labels = []

    def fake_session(url, endpoint, proxy_label):
        labels.append(proxy_label)
        return session

    monkeypatch.setattr(scraper, "_get_session", fake_session)
    monkeypatch.setattr(http_module, "MAX_RETRIES", 2)
    monkeypatch.setattr(http_module.time, "sleep", lambda value: None)

    assert scraper.request_api("https://example.test/data") == {"ok": True}
    assert labels == ["proxy-001", "proxy-002"]
    assert manager.snapshot()["proxies"][0]["rate_limited"] == 1


def test_timeout_is_recorded_and_target_log_is_sanitized(
    monkeypatch,
    caplog,
) -> None:
    manager = build_manager(1)
    scraper = HttpScrapper(proxy_manager=manager)
    session = SequenceSession(
        [requests.Timeout("contains-secret"), requests.Timeout("contains-secret")]
    )
    monkeypatch.setattr(scraper, "_get_session", lambda *args: session)
    monkeypatch.setattr(http_module, "MAX_RETRIES", 2)
    monkeypatch.setattr(http_module.time, "sleep", lambda value: None)

    with caplog.at_level(logging.WARNING), pytest.raises(RetryError) as error:
        scraper.request_api(
            "https://account:password@example.test/data?token=top-secret"
        )

    output = caplog.text + str(error.value)
    assert "account" not in output
    assert "password" not in output
    assert "top-secret" not in output
    assert manager.snapshot()["proxies"][0]["timeouts"] == 2


def test_zero_status_is_a_connection_error_not_a_success(monkeypatch) -> None:
    manager = build_manager(2)
    scraper = HttpScrapper(proxy_manager=manager)
    session = SequenceSession([FakeResponse(0), FakeResponse(0)])
    monkeypatch.setattr(scraper, "_get_session", lambda *args: session)
    monkeypatch.setattr(http_module, "MAX_RETRIES", 2)
    monkeypatch.setattr(http_module.time, "sleep", lambda value: None)

    with pytest.raises(RetryError, match="connection_error"):
        scraper.request_api("https://example.test/data")

    proxies = manager.snapshot()["proxies"]
    assert sum(proxy["successes"] for proxy in proxies) == 0
    assert sum(proxy["errors"] for proxy in proxies) == 2


def test_sessions_are_bound_to_proxy_host_and_worker_thread(monkeypatch) -> None:
    created = []

    class FakeCurlSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.headers = {}
            self.trust_env = True
            created.append(self)

    monkeypatch.setattr(http_module, "CurlSession", FakeCurlSession)
    scraper = HttpScrapper(proxy_manager=build_manager(1))
    proxy = parse_proxy_line(
        "proxy.example:8080:user:secret",
        label="proxy-001",
    )
    main_session = scraper._get_session(
        "https://example.test/data",
        proxy,
        proxy.label,
    )
    assert scraper._get_session(
        "https://example.test/other",
        proxy,
        proxy.label,
    ) is main_session

    worker_session = []

    def create_in_worker() -> None:
        worker_session.append(
            scraper._get_session(
                "https://example.test/data",
                proxy,
                proxy.label,
            )
        )

    thread = threading.Thread(target=create_in_worker)
    thread.start()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert worker_session[0] is not main_session
    assert len(created) == 2
