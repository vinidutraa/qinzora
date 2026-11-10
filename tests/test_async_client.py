import asyncio

import httpx
import pytest

from qinzora.client import AsyncQinzoraClient, QinzoraUnavailable
from qinzora.models import Event


@pytest.mark.parametrize("operation,path", [("observe", "/v1/events"), ("decide", "/v1/decisions")])
def test_async_sdk_sends_event_identity_and_closes(monkeypatch, operation, path):
    event = Event(service="s", route="/r", subject="u")

    async def respond(client, url, **kwargs):
        assert url == path
        assert client.headers["Authorization"] == "Bearer collector-test"
        assert kwargs["json"]["event_id"] == event.event_id
        return httpx.Response(
            200,
            json={
                "allowed": False,
                "event_id": event.event_id,
                "mode": "observe" if operation == "observe" else "enforce",
            },
            request=httpx.Request("POST", "http://test"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", respond)

    async def run():
        async with AsyncQinzoraClient("http://test", "collector-test") as client:
            assert not (await getattr(client, operation)(event))["allowed"]
        assert client.http.is_closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "payload,status", [({}, 200), ({"allowed": 1}, 200), ({"allowed": True}, 503), ([], 200)]
)
def test_async_sdk_does_not_grant_access_on_invalid_response(monkeypatch, payload, status):
    async def respond(*args, **kwargs):
        return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", respond)

    async def run():
        async with AsyncQinzoraClient("http://test", "test") as client:
            with pytest.raises(QinzoraUnavailable):
                await client.decide(Event(service="s", route="/r", subject="u"))

    asyncio.run(run())


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timeout"), asyncio.CancelledError()])
def test_async_sdk_preserves_cancellation_and_handles_timeout(monkeypatch, failure):
    async def respond(*args, **kwargs):
        raise failure

    monkeypatch.setattr(httpx.AsyncClient, "post", respond)

    async def run():
        async with AsyncQinzoraClient("http://test", "test") as client:
            expected = (
                asyncio.CancelledError
                if isinstance(failure, asyncio.CancelledError)
                else QinzoraUnavailable
            )
            with pytest.raises(expected):
                await client.decide(Event(service="s", route="/r", subject="u"))
        assert client.http.is_closed

    asyncio.run(run())
