import asyncio

import httpx
import pytest

from qinzora.client import AsyncQinzoraClient, QinzoraClient, QinzoraUnavailable
from qinzora.models import Event


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("operation,mode", [("observe", "observe"), ("decide", "enforce")])
@pytest.mark.parametrize("invalid_field", ["event_id", "mode", "missing_event_id", "missing_mode"])
def test_sdk_refuses_a_decision_for_another_event_or_operation(
    monkeypatch, asynchronous, operation, mode, invalid_field
):
    event = Event(service="documents", route="/documents", subject="user")
    payload = {"allowed": True, "event_id": event.event_id, "mode": mode}
    if invalid_field.startswith("missing_"):
        payload.pop(invalid_field.removeprefix("missing_"))
    else:
        payload[invalid_field] = "another-event" if invalid_field == "event_id" else "wrong-mode"

    def response(*args, **kwargs):
        return httpx.Response(
            200, json=payload, request=httpx.Request("POST", "http://test/v1/decisions")
        )

    async def async_response(*args, **kwargs):
        return response()

    if asynchronous:
        monkeypatch.setattr(httpx.AsyncClient, "post", async_response)

        async def run():
            async with AsyncQinzoraClient("http://test", "test-key") as client:
                with pytest.raises(QinzoraUnavailable):
                    await getattr(client, operation)(event)

        asyncio.run(run())
    else:
        monkeypatch.setattr(httpx.Client, "post", response)
        with QinzoraClient("http://test", "test-key") as client:
            with pytest.raises(QinzoraUnavailable):
                getattr(client, operation)(event)
