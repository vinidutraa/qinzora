"""Server-side SDK. Never expose collector keys or trust tenant claims from clients."""

from types import TracebackType
from typing import Any, Required, TypedDict, cast

import httpx

from .models import Event


class Decision(TypedDict, total=False):
    """Decision envelope; callers must retain their own authorization checks."""

    allowed: Required[bool]
    event_id: Required[str]
    mode: Required[str]
    findings: list[dict[str, Any]]
    blocks: list[dict[str, Any]]
    received_at: str
    duplicate: bool


def _decision(response: httpx.Response, event_id: str, mode: str) -> Decision:
    response.raise_for_status()
    data = response.json()
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("allowed"), bool)
        or data.get("event_id") != event_id
        or data.get("mode") != mode
    ):
        raise ValueError("Invalid decision response")
    return cast(Decision, data)


class QinzoraUnavailable(RuntimeError):
    pass


class QinzoraClient:
    def __init__(self, base_url: str, collector_key: str, timeout: float = 2) -> None:
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {collector_key}"},
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "QinzoraClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _send(self, path: str, event: Event) -> Decision:
        payload = event.model_dump(mode="json")
        try:
            response = self.http.post(path, json=payload)
            return _decision(
                response, payload["event_id"], "enforce" if path == "/v1/decisions" else "observe"
            )
        except (httpx.HTTPError, ValueError) as exc:
            # Never turn an unavailable guard into an implicit allow.
            raise QinzoraUnavailable("Qinzora did not return a valid decision") from exc

    def observe(self, event: Event) -> Decision:
        return self._send("/v1/events", event)

    def decide(self, event: Event) -> Decision:
        return self._send("/v1/decisions", event)


class AsyncQinzoraClient:
    """Non-blocking SDK for async application lifecycles. No automatic retries.

    Reuse an Event (and its event_id) if the application explicitly retries a
    timed-out call. Cancellation propagates to the caller without granting access.
    """

    def __init__(self, base_url: str, collector_key: str, timeout: float = 2) -> None:
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {collector_key}"},
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> "AsyncQinzoraClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _send(self, path: str, event: Event) -> Decision:
        payload = event.model_dump(mode="json")
        try:
            response = await self.http.post(path, json=payload)
            return _decision(
                response, payload["event_id"], "enforce" if path == "/v1/decisions" else "observe"
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise QinzoraUnavailable("Qinzora did not return a valid decision") from exc

    async def observe(self, event: Event) -> Decision:
        return await self._send("/v1/events", event)

    async def decide(self, event: Event) -> Decision:
        return await self._send("/v1/decisions", event)
