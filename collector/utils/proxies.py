"""Thread-safe, conservative proxy allocation and health tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition
import time
from typing import Callable, Iterable, Optional
from urllib.parse import quote, unquote, urlparse, urlunparse


class ProxyConfigurationError(ValueError):
    """Raised when proxying is enabled with an invalid configuration."""


class ProxyManagerClosed(RuntimeError):
    """Raised when work is requested after shutdown."""


@dataclass(frozen=True, repr=False)
class ProxyEndpoint:
    label: str
    scheme: str
    host: str = field(repr=False)
    port: int = field(repr=False)
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def authenticated_url(self) -> str:
        if not self.username and not self.password:
            return self.base_url
        credentials = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@"
        return f"{self.scheme}://{credentials}{self.host}:{self.port}"

    @property
    def proxy_auth(self) -> tuple[str, str]:
        return self.username, self.password

    @property
    def request_proxies(self) -> dict[str, str]:
        return {"http": self.authenticated_url, "https": self.authenticated_url}


def parse_proxy_line(value: str, *, label: str) -> ProxyEndpoint:
    """Parse a URL or the provider's ``host:port:user:password`` format."""

    raw = value.strip()
    if not raw or raw.startswith("#"):
        raise ProxyConfigurationError("empty proxy entry")

    if "://" not in raw:
        parts = raw.split(":", 3)
        if len(parts) not in (2, 4):
            raise ProxyConfigurationError(
                "proxy entry must use host:port or host:port:user:password"
            )
        host, port_text = parts[:2]
        username, password = parts[2:] if len(parts) == 4 else ("", "")
        scheme = "http"
    else:
        parsed = urlparse(raw)
        scheme = parsed.scheme.casefold()
        host = parsed.hostname or ""
        try:
            port_text = str(parsed.port or "")
        except ValueError as error:
            raise ProxyConfigurationError("proxy port is invalid") from error
        username = unquote(parsed.username or "")
        password = unquote(parsed.password or "")

    if scheme not in {"http", "https"}:
        raise ProxyConfigurationError("only HTTP and HTTPS proxies are supported")
    if not host.strip():
        raise ProxyConfigurationError("proxy hostname is missing")
    try:
        port = int(port_text)
    except ValueError as error:
        raise ProxyConfigurationError("proxy port is invalid") from error
    if not 1 <= port <= 65535:
        raise ProxyConfigurationError("proxy port is outside 1..65535")
    if bool(username) != bool(password):
        raise ProxyConfigurationError(
            "proxy username and password must be provided together"
        )
    return ProxyEndpoint(
        label=label,
        scheme=scheme,
        host=host.strip(),
        port=port,
        username=username,
        password=password,
    )


def load_proxy_file(path: str | Path) -> tuple[ProxyEndpoint, ...]:
    proxy_path = Path(path)
    try:
        lines = proxy_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ProxyConfigurationError(
            f"cannot read proxy file: {proxy_path.name}"
        ) from error

    entries = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not entries:
        raise ProxyConfigurationError("proxy file contains no entries")

    proxies = tuple(
        parse_proxy_line(entry, label=f"proxy-{index:03d}")
        for index, entry in enumerate(entries, start=1)
    )
    identities = {(proxy.scheme, proxy.host, proxy.port) for proxy in proxies}
    if len(identities) != len(proxies):
        raise ProxyConfigurationError("proxy file contains duplicate endpoints")
    return proxies


@dataclass
class ProxyStats:
    endpoint: ProxyEndpoint
    active: int = 0
    requests: int = 0
    successes: int = 0
    timeouts: int = 0
    errors: int = 0
    rate_limited: int = 0
    forbidden: int = 0
    authentication_failures: int = 0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    latency_total: float = 0.0
    next_request_at: float = 0.0


@dataclass(frozen=True)
class ProxyLease:
    manager: "ProxyManager"
    endpoint: Optional[ProxyEndpoint]
    label: str

    def release(self) -> None:
        self.manager.release(self)

    def __enter__(self) -> "ProxyLease":
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


class ProxyManager:
    """Allocate proxies without multiplying the source-wide request budget."""

    def __init__(
        self,
        proxies: Iterable[ProxyEndpoint],
        *,
        global_concurrency: int,
        global_requests_per_minute: int,
        requests_per_minute_per_proxy: int,
        concurrent_requests_per_proxy: int,
        failure_threshold: int,
        cooldown_seconds: float,
        allow_direct_fallback: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        values = {
            "global_concurrency": global_concurrency,
            "global_requests_per_minute": global_requests_per_minute,
            "requests_per_minute_per_proxy": requests_per_minute_per_proxy,
            "concurrent_requests_per_proxy": concurrent_requests_per_proxy,
            "failure_threshold": failure_threshold,
        }
        if any(value < 1 for value in values.values()):
            raise ProxyConfigurationError("proxy limits must be positive")
        if cooldown_seconds < 0:
            raise ProxyConfigurationError("proxy cooldown cannot be negative")

        self._states = [ProxyStats(proxy) for proxy in proxies]
        if not self._states and not allow_direct_fallback:
            raise ProxyConfigurationError(
                "no proxies configured and direct fallback is disabled"
            )
        self._global_concurrency = global_concurrency
        self._effective_concurrency = global_concurrency
        self._global_rpm = global_requests_per_minute
        self._proxy_rpm = requests_per_minute_per_proxy
        self._per_proxy_concurrency = concurrent_requests_per_proxy
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._allow_direct = allow_direct_fallback
        self._clock = clock
        self._condition = Condition()
        self._global_active = 0
        self._direct_active = 0
        self._global_next_request_at = 0.0
        self._direct_next_request_at = 0.0
        self._global_penalty_until = 0.0
        self._closed = False
        self._cursor = 0

    def acquire(self) -> ProxyLease:
        with self._condition:
            while True:
                if self._closed:
                    raise ProxyManagerClosed("proxy manager is closed")
                now = self._clock()
                if now >= self._global_penalty_until:
                    self._effective_concurrency = self._global_concurrency

                global_wait = max(0.0, self._global_next_request_at - now)
                if self._global_active >= self._effective_concurrency:
                    self._condition.wait(timeout=0.1)
                    continue
                if global_wait > 0:
                    self._condition.wait(timeout=min(global_wait, 1.0))
                    continue

                candidates = []
                proxy_waits = []
                for offset in range(len(self._states)):
                    index = (self._cursor + offset) % len(self._states)
                    state = self._states[index]
                    if state.cooldown_until > now:
                        proxy_waits.append(state.cooldown_until - now)
                        continue
                    if state.active >= self._per_proxy_concurrency:
                        continue
                    wait = max(0.0, state.next_request_at - now)
                    if wait > 0:
                        proxy_waits.append(wait)
                        continue
                    candidates.append((state.active, state.requests, offset, index, state))

                if candidates:
                    _, _, _, index, state = min(candidates)
                    self._cursor = (index + 1) % len(self._states)
                    state.active += 1
                    state.requests += 1
                    state.next_request_at = max(
                        now,
                        state.next_request_at,
                    ) + 60 / self._proxy_rpm
                    self._global_active += 1
                    self._global_next_request_at = max(
                        now,
                        self._global_next_request_at,
                    ) + 60 / self._global_rpm
                    return ProxyLease(self, state.endpoint, state.endpoint.label)

                all_unavailable = not self._states or all(
                    state.cooldown_until > now for state in self._states
                )
                if (
                    self._allow_direct
                    and all_unavailable
                    and self._direct_active < 1
                    and self._direct_next_request_at <= now
                ):
                    direct_rpm = (
                        self._proxy_rpm if self._states else self._global_rpm
                    )
                    self._direct_active += 1
                    self._global_active += 1
                    self._direct_next_request_at = now + 60 / direct_rpm
                    self._global_next_request_at = max(
                        now,
                        self._global_next_request_at,
                    ) + 60 / self._global_rpm
                    return ProxyLease(self, None, "direct")

                timeout = min(proxy_waits) if proxy_waits else 0.1
                self._condition.wait(timeout=max(0.01, min(timeout, 1.0)))

    def _state_for(self, lease: ProxyLease) -> Optional[ProxyStats]:
        if lease.endpoint is None:
            return None
        return next(
            state for state in self._states if state.endpoint is lease.endpoint
        )

    def release(self, lease: ProxyLease) -> None:
        with self._condition:
            state = self._state_for(lease)
            if state is None:
                self._direct_active = max(0, self._direct_active - 1)
            else:
                state.active = max(0, state.active - 1)
            self._global_active = max(0, self._global_active - 1)
            self._condition.notify_all()

    def report(
        self,
        lease: ProxyLease,
        *,
        latency: float,
        status_code: int | str,
        retry_after: float | None = None,
    ) -> None:
        with self._condition:
            state = self._state_for(lease)
            if state is None:
                return
            state.latency_total += max(0.0, latency)
            now = self._clock()
            if isinstance(status_code, int) and 200 <= status_code < 400:
                state.successes += 1
                state.consecutive_failures = 0
            elif status_code == 429:
                state.rate_limited += 1
                state.consecutive_failures += 1
                cooldown = max(self._cooldown_seconds, retry_after or 0)
                state.cooldown_until = max(state.cooldown_until, now + cooldown)
                self._effective_concurrency = max(
                    1,
                    self._effective_concurrency // 2,
                )
                self._global_penalty_until = max(
                    self._global_penalty_until,
                    now + cooldown,
                )
            elif status_code == 403:
                state.forbidden += 1
                state.consecutive_failures += 1
                state.cooldown_until = max(
                    state.cooldown_until,
                    now + self._cooldown_seconds,
                )
            elif status_code == 407:
                state.authentication_failures += 1
                state.errors += 1
                state.consecutive_failures += 1
                state.cooldown_until = max(
                    state.cooldown_until,
                    now + self._cooldown_seconds,
                )
            elif status_code == 404:
                # A source 404 proves that the proxy is reachable and says
                # nothing negative about proxy health.
                state.successes += 1
                state.consecutive_failures = 0
            else:
                if status_code == "timeout":
                    state.timeouts += 1
                    state.cooldown_until = max(
                        state.cooldown_until,
                        now + self._cooldown_seconds,
                    )
                else:
                    state.errors += 1
                state.consecutive_failures += 1
                if (
                    status_code != "timeout"
                    and state.consecutive_failures >= self._failure_threshold
                ):
                    state.cooldown_until = max(
                        state.cooldown_until,
                        now + self._cooldown_seconds,
                    )
            self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            now = self._clock()
            proxies = tuple(
                {
                    "label": state.endpoint.label,
                    "active": state.active,
                    "requests": state.requests,
                    "successes": state.successes,
                    "timeouts": state.timeouts,
                    "errors": state.errors,
                    "rate_limited": state.rate_limited,
                    "forbidden": state.forbidden,
                    "authentication_failures": state.authentication_failures,
                    "average_latency": (
                        state.latency_total / state.requests
                        if state.requests
                        else 0.0
                    ),
                    "in_cooldown": state.cooldown_until > now,
                }
                for state in self._states
            )
            cooldown_count = sum(
                1 for state in self._states if state.cooldown_until > now
            )
            return {
                "global_active": self._global_active,
                "effective_concurrency": self._effective_concurrency,
                "active_proxies": len(self._states) - cooldown_count,
                "cooldown_proxies": cooldown_count,
                "unavailable_proxies": 0,
                "proxies": proxies,
            }

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


def redact_url(value: str) -> str:
    """Remove credentials, query parameters and fragments before logging."""

    parsed = urlparse(value)
    host = parsed.hostname or ""
    netloc = host + (f":{parsed.port}" if parsed.port else "")
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
