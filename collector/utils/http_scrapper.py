import random
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import cloudscraper
import requests
from curl_cffi.requests import RequestsError as CurlRequestsError
from curl_cffi.requests import Session as CurlSession
from fake_useragent import UserAgent

from collector.settings import REQUEST_TIMEOUT_SECONDS
from collector.utils.logger import get_logger
from collector.utils.metrics import HTTP_ERRORS_TOTAL, HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL
from collector.utils.proxies import get_curl_proxy_config, request_proxies

logger = get_logger(__name__)


class RetryError(Exception):
    pass


class HttpScrapper:
    def __init__(self, requests_per_minute: int = 30, use_cloudscraper: bool = False):
        self.min_request_interval = 60 / requests_per_minute if requests_per_minute > 0 else 0
        self.last_request_time = 0.0
        self.user_agent = UserAgent()
        self.use_cloudscraper = use_cloudscraper
        self.sessions: Dict[str, Any] = {}
        self.curl_proxy = get_curl_proxy_config()

    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": self.user_agent.random, "Accept": "*/*", "Cache-Control": "no-cache"}

    def _get_session(self, url: str):
        host = urlparse(url).netloc
        if host not in self.sessions:
            if self.curl_proxy:
                session = CurlSession(proxies=self.curl_proxy.proxies,
                                      proxy_auth=self.curl_proxy.proxy_auth,
                                      trust_env=False, impersonate="chrome")
            elif self.use_cloudscraper:
                session = cloudscraper.create_scraper()
            else:
                session = requests.Session()
            session.headers.update(self._headers())
            session.trust_env = False
            self.sessions[host] = session
        return self.sessions[host]

    def _rate_limit(self) -> None:
        remaining = self.min_request_interval - (time.time() - self.last_request_time)
        if remaining > 0:
            time.sleep(remaining * random.uniform(0.8, 1.2))
        time.sleep(random.uniform(0, 0.2))
        self.last_request_time = time.time()

    def request_api(self, url: str, method: str = "GET", params: Optional[Dict] = None,
                    extra_headers: Optional[Dict] = None, data: Any = None,
                    query: Any = None, json_response: bool = True):
        self._rate_limit()
        host = urlparse(url).netloc
        session = self._get_session(url)
        proxies = None if self.curl_proxy else request_proxies()
        for attempt in range(3):
            started = time.time()
            try:
                HTTP_REQUESTS_TOTAL.labels(source=host, method=method).inc()
                response = session.request(method=method, url=url, json=query, data=data,
                                           headers=extra_headers, params=params,
                                           proxies=proxies, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                HTTP_REQUEST_DURATION.labels(source=host).observe(time.time() - started)
                return response.json() if json_response else response
            except (requests.RequestException, CurlRequestsError) as error:
                status = getattr(getattr(error, "response", None), "status_code", "connection_error")
                HTTP_ERRORS_TOTAL.labels(source=host, status_code=status).inc()
                if status == 404:
                    return None
                logger.warning("Request failed (%s), attempt %s/3: %s", status, attempt + 1, url)
                time.sleep(2 ** attempt)
        raise RetryError(f"Request failed after 3 attempts: {url}")

    def close(self) -> None:
        for session in self.sessions.values():
            close = getattr(session, "close", None)
            if close:
                close()
        self.sessions.clear()
