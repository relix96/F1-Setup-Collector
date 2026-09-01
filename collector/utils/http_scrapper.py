"""Shared HTTP client with bounded concurrency, retries and proxy health."""

from __future__ import annotations

import random
from threading import Lock, get_ident
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import cloudscraper
import requests
from curl_cffi.requests import RequestsError as CurlRequestsError
from curl_cffi.requests import Session as CurlSession
from fake_useragent import UserAgent

from collector.settings import (
    COLLECTOR_CONCURRENCY,
    MAX_CONCURRENT_REQUESTS_PER_PROXY,
    MAX_REQUESTS_PER_MINUTE_PER_PROXY,
    MAX_RETRIES,
    PROXY_ALLOW_DIRECT_FALLBACK,
    PROXY_COOLDOWN_SECONDS,
    PROXY_ENABLED,
    PROXY_FAILURE_THRESHOLD,
    PROXY_FILE,
    REQUEST_TIMEOUT_SECONDS,
)
from collector.utils.logger import get_logger
from collector.utils.metrics import (
    HTTP_ERRORS_TOTAL,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
)
from collector.utils.proxies import (
    ProxyEndpoint,
    ProxyManager,
    load_proxy_file,
    redact_url,
)

logger = get_logger(__name__)


class RetryError(Exception):
    pass


def build_proxy_manager(
    requests_per_minute: int,
    *,
    proxy_enabled: bool,
) -> ProxyManager:
    proxies = load_proxy_file(PROXY_FILE) if proxy_enabled else ()
    return ProxyManager(
        proxies,
        global_concurrency=COLLECTOR_CONCURRENCY,
        global_requests_per_minute=requests_per_minute,
        requests_per_minute_per_proxy=MAX_REQUESTS_PER_MINUTE_PER_PROXY,
        concurrent_requests_per_proxy=MAX_CONCURRENT_REQUESTS_PER_PROXY,
        failure_threshold=PROXY_FAILURE_THRESHOLD,
        cooldown_seconds=PROXY_COOLDOWN_SECONDS,
        allow_direct_fallback=(
            PROXY_ALLOW_DIRECT_FALLBACK if proxy_enabled else True
        ),
    )


class HttpScrapper:
    def __init__(
        self,
        requests_per_minute: int = 30,
        use_cloudscraper: bool = False,
        proxy_manager: ProxyManager | None = None,
        proxy_enabled: bool | None = None,
    ) -> None:
        self.user_agent = UserAgent()
        self.use_cloudscraper = use_cloudscraper
        self.sessions: Dict[tuple[str, str, int], Any] = {}
        self._sessions_lock = Lock()
        self._metrics_lock = Lock()
        self._started_at = time.monotonic()
        self._request_count = 0
        self._error_count = 0
        self._latency_total = 0.0
        self.proxy_manager = proxy_manager or build_proxy_manager(
            requests_per_minute,
            proxy_enabled=(
                PROXY_ENABLED if proxy_enabled is None else proxy_enabled
            ),
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent.random,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        }

    def _get_session(
        self,
        url: str,
        endpoint: ProxyEndpoint | None,
        proxy_label: str,
    ) -> Any:
        host = urlparse(url).netloc
        key = (host, proxy_label, get_ident())
        with self._sessions_lock:
            if key in self.sessions:
                return self.sessions[key]
            if endpoint is not None:
                session = CurlSession(
                    proxies={
                        "http": endpoint.base_url,
                        "https": endpoint.base_url,
                    },
                    proxy_auth=endpoint.proxy_auth,
                    trust_env=False,
                    impersonate="chrome",
                )
            elif self.use_cloudscraper:
                session = cloudscraper.create_scraper()
            else:
                session = requests.Session()
            session.headers.update(self._headers())
            session.trust_env = False
            self.sessions[key] = session
            return session

    @staticmethod
    def _retry_after(response: Any) -> float | None:
        value = getattr(response, "headers", {}).get("Retry-After")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _transport_error_status(error: Exception) -> int | str:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and status > 0:
            return status

        error_code = getattr(error, "code", None)
        if error_code == 28 or "timeout" in type(error).__name__.casefold():
            return "timeout"

        # curl reports a failed CONNECT tunnel as code 56 and keeps the HTTP
        # status at zero. Extract only the known status marker; never log the
        # exception text because it may contain proxy credentials.
        message = str(error).casefold()
        if error_code == 56 and "407" in message:
            return 407
        return "connection_error"

    def request_api(
        self,
        url: str,
        method: str = "GET",
        params: Optional[Dict] = None,
        extra_headers: Optional[Dict] = None,
        data: Any = None,
        query: Any = None,
        json_response: bool = True,
    ) -> Any:
        host = urlparse(url).netloc
        safe_target = redact_url(url)
        last_status: int | str = "connection_error"

        for attempt in range(MAX_RETRIES):
            with self.proxy_manager.acquire() as lease:
                session = self._get_session(url, lease.endpoint, lease.label)
                proxies = (
                    lease.endpoint.request_proxies
                    if lease.endpoint is not None
                    and not isinstance(session, CurlSession)
                    else None
                )
                started = time.monotonic()
                try:
                    HTTP_REQUESTS_TOTAL.labels(source=host, method=method).inc()
                    with self._metrics_lock:
                        self._request_count += 1
                    response = session.request(
                        method=method,
                        url=url,
                        json=query,
                        data=data,
                        headers=extra_headers,
                        params=params,
                        proxies=proxies,
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    latency = time.monotonic() - started
                    status = int(response.status_code)
                    last_status = status if status > 0 else "connection_error"
                    self.proxy_manager.report(
                        lease,
                        latency=latency,
                        status_code=last_status,
                        retry_after=self._retry_after(response),
                    )
                    HTTP_REQUEST_DURATION.labels(source=host).observe(latency)
                    with self._metrics_lock:
                        self._latency_total += latency
                    if last_status == 404:
                        return None
                    if isinstance(last_status, int) and last_status < 400:
                        return response.json() if json_response else response
                    HTTP_ERRORS_TOTAL.labels(
                        source=host,
                        status_code=last_status,
                    ).inc()
                    with self._metrics_lock:
                        self._error_count += 1
                except (requests.RequestException, CurlRequestsError) as error:
                    latency = time.monotonic() - started
                    response = getattr(error, "response", None)
                    last_status = self._transport_error_status(error)
                    self.proxy_manager.report(
                        lease,
                        latency=latency,
                        status_code=last_status,
                        retry_after=(
                            self._retry_after(response)
                            if response is not None
                            else None
                        ),
                    )
                    HTTP_ERRORS_TOTAL.labels(
                        source=host,
                        status_code=last_status,
                    ).inc()
                    with self._metrics_lock:
                        self._error_count += 1
                        self._latency_total += latency

            logger.warning(
                "Request failed status=%s attempt=%s/%s proxy=%s target=%s",
                last_status,
                attempt + 1,
                MAX_RETRIES,
                lease.label,
                safe_target,
            )
            if attempt + 1 < MAX_RETRIES:
                backoff = min(30.0, 2**attempt) + random.uniform(0.0, 1.0)
                time.sleep(backoff)

        raise RetryError(
            f"request failed after {MAX_RETRIES} attempts "
            f"(status={last_status}, target={safe_target})"
        )

    def close(self) -> None:
        with self._sessions_lock:
            sessions = tuple(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            close = getattr(session, "close", None)
            if close:
                close()

        snapshot = self.proxy_manager.snapshot()
        elapsed = max(0.001, time.monotonic() - self._started_at)
        with self._metrics_lock:
            request_count = self._request_count
            error_count = self._error_count
            latency_total = self._latency_total
        logger.info(
            "HTTP summary requests=%d errors=%d success_rate=%.2f%% "
            "requests_per_minute=%.2f latency_avg=%.3fs active_proxies=%s "
            "cooldown_proxies=%s unavailable_proxies=%s",
            request_count,
            error_count,
            (
                100 * (request_count - error_count) / request_count
                if request_count
                else 100.0
            ),
            request_count * 60 / elapsed,
            latency_total / request_count if request_count else 0.0,
            snapshot["active_proxies"],
            snapshot["cooldown_proxies"],
            snapshot["unavailable_proxies"],
        )
        for proxy in snapshot["proxies"]:
            logger.info(
                "Proxy summary label=%s requests=%s successes=%s timeouts=%s "
                "errors=%s rate_limited=%s forbidden=%s auth_failures=%s "
                "latency_avg=%.3fs cooldown=%s",
                proxy["label"],
                proxy["requests"],
                proxy["successes"],
                proxy["timeouts"],
                proxy["errors"],
                proxy["rate_limited"],
                proxy["forbidden"],
                proxy["authentication_failures"],
                proxy["average_latency"],
                proxy["in_cooldown"],
            )
        self.proxy_manager.close()
