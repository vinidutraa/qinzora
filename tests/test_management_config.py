import asyncio
import json

import httpx
import pytest
from test_api import post_event

from qinzora.administration.config import ManagementConfig, run_cycle
from qinzora.providers import HTTPStructuredModel


@pytest.mark.parametrize("execute", [False, True])
def test_configured_http_model_drives_a_real_policy_cycle(api, tenant, event, monkeypatch, execute):
    client, _ = api
    post_event(client, tenant, {**event, "expected": "legitimate"})
    post_event(
        client, tenant, {**event, "event_id": "bad", "resource_tenant": "b", "expected": "abusive"}
    )
    proposal = {
        "rationale": "Observed cross-tenant attempts",
        "operations": [
            {
                "action": "enforce_policy",
                "policy": {
                    "name": "agent isolation",
                    "service": "documents",
                    "kind": "tenant_isolation",
                    "ttl_seconds": 60,
                },
            }
        ],
    }

    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "user-chosen-model"
        assert request.headers["authorization"] == "Bearer model-secret"
        assert "model-secret" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {"content": json.dumps(proposal)},
            },
        )

    def provider(*args, **kwargs):
        return HTTPStructuredModel(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr("qinzora.administration.config.HTTPStructuredModel", provider)
    monkeypatch.setenv("QINZORA_TEST_MODEL_KEY", "model-secret")
    config = ManagementConfig(
        database=str(client.app.state.store.path),
        account_id=tenant["id"],
        provider="ollama",
        base_url="http://model.test",
        model="user-chosen-model",
        api_key_env="QINZORA_TEST_MODEL_KEY",
        authority={"routes": [{"service": "documents", "route": "*"}], "allow_enforce": True},
    )
    result = asyncio.run(run_cycle(config, execute=execute))
    assert result["state"] == ("executed" if execute else "draft")
    assert "context" not in result and "model-secret" not in json.dumps(result)
    decision = post_event(
        client,
        tenant,
        {**event, "event_id": "after", "resource_tenant": "b", "expected": "abusive"},
        "decisions",
    ).json()
    assert decision["allowed"] is not execute
    if not execute:

        def unexpected_call(request):
            pytest.fail("Executing a saved plan must not call the model again")

        monkeypatch.setattr(
            "qinzora.administration.config.HTTPStructuredModel",
            lambda *args, **kwargs: HTTPStructuredModel(
                *args, **kwargs, transport=httpx.MockTransport(unexpected_call)
            ),
        )
        monkeypatch.delenv("QINZORA_TEST_MODEL_KEY")
        executed = asyncio.run(run_cycle(config, execute=True, plan_id=result["id"]))
        assert executed["state"] == "executed" and executed["id"] == result["id"]
        assert not post_event(
            client,
            tenant,
            {**event, "event_id": "blocked-after-review", "resource_tenant": "b"},
            "decisions",
        ).json()["allowed"]


def test_missing_database_is_not_silently_created(tmp_path):
    target = tmp_path / "missing.sqlite"
    config = ManagementConfig(
        database=str(target),
        account_id="missing",
        provider="ollama",
        base_url="http://model.test",
        model="m",
        authority={"routes": [{"service": "s", "route": "*"}]},
    )
    with pytest.raises(ValueError, match="does not exist"):
        asyncio.run(run_cycle(config))
    assert not target.exists()
