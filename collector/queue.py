"""Best-effort Redis notification for durable setup work stored in MongoDB."""

from __future__ import annotations

from typing import Any


class RedisSetupPublisher:
    """Publish MongoDB document IDs without making Redis the source of truth."""

    def __init__(self, client: Any, stream: str) -> None:
        self._client = client
        self._stream = stream

    @classmethod
    def from_url(cls, url: str, stream: str) -> "RedisSetupPublisher | None":
        if not url.strip():
            return None

        from redis import Redis

        return cls(
            Redis.from_url(url, decode_responses=True),
            stream,
        )

    def publish(self, document_id: str) -> str:
        return str(
            self._client.xadd(
                self._stream,
                {"mongo_document_id": document_id},
            )
        )

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()
