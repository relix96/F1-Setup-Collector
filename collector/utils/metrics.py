class _Metric:
    def labels(self, **kwargs):
        return self

    def inc(self, amount: int = 1) -> None:
        return None

    def observe(self, value: float) -> None:
        return None


HTTP_REQUESTS_TOTAL = _Metric()
HTTP_ERRORS_TOTAL = _Metric()
HTTP_REQUEST_DURATION = _Metric()
