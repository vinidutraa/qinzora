import asyncio
import json
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from qinzora.providers import HTTPStructuredModel, ModelUnavailable


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["observe", "simulate"]


def envelope(provider, content):
    if provider == "ollama":
        return {"done": True, "done_reason": "stop", "message": {"content": content}}
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


@pytest.mark.parametrize(
    "provider,path",
    [("ollama", "/prefix/api/chat"), ("chat_completions", "/prefix/chat/completions")],
)
def test_provider_sends_schema_and_validates_response(provider, path):
    def respond(request):
        assert request.url.path == path
        assert request.headers["authorization"] == "Bearer private-test-key"
        body = json.loads(request.content)
        assert body["model"] == "chosen-model" and body["stream"] is False
        assert "private-test-key" not in request.content.decode()
        schema = (
            body["format"]
            if provider == "ollama"
            else body["response_format"]["json_schema"]["schema"]
        )
        assert schema == Proposal.model_json_schema()
        assert json.loads(body["messages"][1]["content"]) == {"errors": 2}
        return httpx.Response(200, json=envelope(provider, '{"action":"simulate"}'))

    async def run():
        async with HTTPStructuredModel(
            provider,
            "https://model.test/prefix",
            "chosen-model",
            api_key="private-test-key",
            transport=httpx.MockTransport(respond),
        ) as model:
            result = await model.generate("Choose an action", {"errors": 2}, Proposal)
            assert result.action == "simulate"
        assert model.http.is_closed

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["ollama", "chat_completions"])
@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        "null",
        '{"action":"delete_database"}',
        '{"action":"observe","shell":"private-test-key"}',
        "",
    ],
)
def test_invalid_model_proposal_never_becomes_an_action(provider, content):
    async def run():
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, json=envelope(provider, content))
        )
        async with HTTPStructuredModel(
            provider, "http://model.test", "model", transport=transport
        ) as model:
            with pytest.raises(ModelUnavailable) as failure:
                await model.generate("s", {}, Proposal)
            assert content not in str(failure.value) or not content
            assert failure.value.__suppress_context__

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,payload,status",
    [
        ("ollama", {"done": False, "message": {"content": '{"action":"observe"}'}}, 200),
        ("ollama", {"done": True, "done_reason": "length", "message": {}}, 200),
        ("chat_completions", {"choices": []}, 200),
        ("chat_completions", {"choices": [{"message": []}]}, 200),
        ("chat_completions", {"choices": [None]}, 200),
        ("ollama", [], 200),
        ("chat_completions", {"choices": [{"finish_reason": "length", "message": {}}]}, 200),
        ("ollama", {"detail": "private-test-key"}, 401),
        ("ollama", None, 200),
        ("ollama", {"data": "x" * 270000}, 200),
    ],
)
def test_failures_and_truncated_responses_are_rejected(provider, payload, status):
    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(status, json=payload))
        async with HTTPStructuredModel(
            provider, "http://model.test", "model", transport=transport
        ) as model:
            with pytest.raises(ModelUnavailable, match="complete, valid"):
                await model.generate("s", {}, Proposal)

    asyncio.run(run())


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("private-key"), asyncio.CancelledError()])
def test_transport_failure_and_cancellation_close_lifecycle(failure):
    async def respond(request):
        raise failure

    async def run():
        with pytest.raises(
            asyncio.CancelledError
            if isinstance(failure, asyncio.CancelledError)
            else ModelUnavailable
        ):
            async with HTTPStructuredModel(
                "ollama", "http://model.test", "model", transport=httpx.MockTransport(respond)
            ) as model:
                await model.generate("s", {}, Proposal)
        assert model.http.is_closed

    asyncio.run(run())


@pytest.mark.parametrize("base_url", ["file:///x", "http://user:pass@host", "https://host?key=x"])
def test_model_endpoint_configuration_rejects_embedded_credentials(base_url):
    with pytest.raises(ValueError):
        HTTPStructuredModel("ollama", base_url, "model")
