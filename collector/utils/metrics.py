"""Prometheus metrics for collector runs, HTTP traffic and proxy health."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import HTTPServer
from threading import Thread
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

COLLECTOR_RUNS_TOTAL = Counter("setup_collector_runs_total", "Collector executions.", ("source", "game", "outcome"))
COLLECTOR_RUN_DURATION = Histogram("setup_collector_run_duration_seconds", "Duration of each collector execution.", ("source", "game"))
COLLECTOR_RECORDS_TOTAL = Counter("setup_collector_records_total", "Raw setup records collected and persisted.", ("source", "game", "outcome"))
COLLECTOR_LAST_SUCCESS = Gauge("setup_collector_last_success_timestamp_seconds", "Unix timestamp of the most recent successful collector execution.", ("source", "game"))
COLLECTION_RUN_DURATION = Histogram("setup_collection_run_duration_seconds", "Duration of a complete multi-source collection run.")
COLLECTION_RUNS_TOTAL = Counter("setup_collection_runs_total", "Complete multi-source collection runs.", ("outcome",))
REDIS_PUBLISH_TOTAL = Counter("setup_collector_redis_publish_total", "Redis setup notifications published by the collector.", ("outcome",))
HTTP_REQUESTS_TOTAL = Counter("setup_collector_http_requests_total", "HTTP requests made by collectors.", ("source", "method", "status_class"))
HTTP_ERRORS_TOTAL = Counter("setup_collector_http_errors_total", "HTTP request failures.", ("source", "reason"))
HTTP_REQUEST_DURATION = Histogram("setup_collector_http_request_duration_seconds", "Collector HTTP request latency.", ("source",))
HTTP_RETRIES_TOTAL = Counter("setup_collector_http_retries_total", "Collector HTTP retries.", ("source", "reason"))
HTTP_429_TOTAL = Counter("setup_collector_http_429_total", "HTTP 429 responses received by collectors.", ("source",))
HTTP_TIMEOUTS_TOTAL = Counter("setup_collector_http_timeouts_total", "Collector HTTP timeouts.", ("source",))
PROXY_STATES = Gauge("setup_collector_proxy_states", "Current number of configured proxies by health state.", ("state",))

@dataclass(slots=True)
class MetricsServer:
    server: HTTPServer
    thread: Thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

def start_metrics_server(address: str, port: int) -> MetricsServer:
    server, thread = start_http_server(port, addr=address)
    return MetricsServer(server=server, thread=thread)

def status_class(status: int | str) -> str:
    if isinstance(status, int) and status > 0:
        return f"{status // 100}xx"
    return str(status)

def update_proxy_state_metrics(snapshot: dict[str, Any]) -> None:
    PROXY_STATES.labels(state="active").set(snapshot["active_proxies"])
    PROXY_STATES.labels(state="cooldown").set(snapshot["cooldown_proxies"])
    PROXY_STATES.labels(state="unavailable").set(snapshot["unavailable_proxies"])
