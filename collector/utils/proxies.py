from typing import Dict, NamedTuple, Optional, Tuple
from urllib.parse import unquote, urlparse, urlunparse

from collector.settings import PROXY_URL


def get_http_proxy_url() -> Optional[str]:
    url = PROXY_URL.strip()
    if not url:
        return None
    return url if "://" in url else f"http://{url}"


def request_proxies() -> Optional[Dict[str, str]]:
    url = get_http_proxy_url()
    return {"http": url, "https": url} if url else None


class CurlProxyConfig(NamedTuple):
    proxies: Dict[str, str]
    proxy_auth: Tuple[str, str]


def get_curl_proxy_config() -> Optional[CurlProxyConfig]:
    url = get_http_proxy_url()
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("Invalid PROXY_URL: missing hostname")
    netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    base = urlunparse((parsed.scheme or "http", netloc, "", "", "", ""))
    auth = (unquote(parsed.username or ""), unquote(parsed.password or ""))
    return CurlProxyConfig({"http": base, "https": base}, auth)
