import urllib.request

from collector.utils.metrics import start_metrics_server, status_class


def test_status_class_has_bounded_values() -> None:
    assert status_class(200) == "2xx"
    assert status_class(429) == "4xx"
    assert status_class("timeout") == "timeout"


def test_internal_metrics_server_exposes_prometheus_format() -> None:
    server = start_metrics_server("127.0.0.1", 0)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server.server_port}/metrics",
            timeout=2,
        ) as response:
            content = response.read().decode("utf-8")
    finally:
        server.close()
    assert "setup_collector_http_requests_total" in content
    assert (
        "setup_collector_scheduler_last_successful_slot_timestamp_seconds"
        in content
    )
