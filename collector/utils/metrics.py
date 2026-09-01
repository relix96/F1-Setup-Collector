"""Small in-process metrics registry suitable for batch collector logs."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import DefaultDict


class _BoundMetric:
    def __init__(self, metric: "_Metric", labels: tuple[tuple[str, str], ...]) -> None:
        self._metric = metric
        self._labels = labels

    def inc(self, amount: int = 1) -> None:
        self._metric._inc(self._labels, amount)

    def observe(self, value: float) -> None:
        self._metric._observe(self._labels, value)


class _Metric:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: DefaultDict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._observations: DefaultDict[
            tuple[tuple[str, str], ...], list[float]
        ] = defaultdict(list)

    def labels(self, **kwargs: object) -> _BoundMetric:
        labels = tuple(sorted((key, str(value)) for key, value in kwargs.items()))
        return _BoundMetric(self, labels)

    def _inc(self, labels: tuple[tuple[str, str], ...], amount: int) -> None:
        with self._lock:
            self._counts[labels] += amount

    def _observe(self, labels: tuple[tuple[str, str], ...], value: float) -> None:
        with self._lock:
            self._observations[labels].append(value)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counts": dict(self._counts),
                "observations": {
                    labels: {
                        "count": len(values),
                        "average": sum(values) / len(values) if values else 0.0,
                    }
                    for labels, values in self._observations.items()
                },
            }


HTTP_REQUESTS_TOTAL = _Metric()
HTTP_ERRORS_TOTAL = _Metric()
HTTP_REQUEST_DURATION = _Metric()
