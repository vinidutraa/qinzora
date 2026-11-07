from datetime import timedelta

import httpx
import pytest

from api_sentinel.client import SentinelClient, SentinelUnavailable
from api_sentinel.demo import run_demo
from api_sentinel.engine import evaluate, regressions, simulate
from api_sentinel.explain import explain
from api_sentinel.models import Event, Policy, RouteContract, now


def evt(**kwargs):
    return Event(service="svc", route="/items/{id}", subject="a", **kwargs)


def test_rate_boundary_and_identity_isolation():
    policy = Policy(name="rate", service="svc", kind="rate_limit", threshold=1, window_seconds=10)
    stamp = now()
    event = evt()
    old = {"event": event, "at": stamp - timedelta(seconds=10)}
    recent = {"event": event, "at": stamp - timedelta(seconds=9)}
    assert evaluate(policy, event, stamp, [old]) is None
    assert evaluate(policy, event, stamp, [recent]) == "request_rate_exceeded"
    assert evaluate(policy, event.model_copy(update={"subject": "b"}), stamp, [recent]) is None
    assert evaluate(policy, event.model_copy(update={"service": "other"}), stamp, [recent]) is None


def test_tenant_context_missing_and_mismatch():
    policy = Policy(name="tenant", service="svc", kind="tenant_isolation")
    assert evaluate(policy, evt(), now(), []) == "missing_tenant_context"
    assert (
        evaluate(policy, evt(actor_tenant="a", resource_tenant="b"), now(), [])
        == "cross_tenant_access"
    )
    assert evaluate(policy, evt(actor_tenant="a", resource_tenant="a"), now(), []) is None


def test_completed_response_detectors():
    stamp = now()
    error_policy = Policy(name="error", service="svc", kind="error_burst", threshold=2)
    history = [{"event": evt(status_code=500), "at": stamp}]
    assert evaluate(error_policy, evt(status_code=401), stamp, history) == "error_burst"
    assert evaluate(error_policy, evt(status_code=200), stamp, history) is None
    latency = Policy(name="slow", service="svc", kind="latency", threshold=200)
    assert evaluate(latency, evt(latency_ms=201), stamp, []) == "high_latency"


def test_replay_false_positive_labels_and_unknowns():
    policy = Policy(name="rate", service="svc", kind="rate_limit", threshold=1)
    stamp = now()
    rows = [
        {"event": evt(event_id=str(i), expected=label), "at": stamp}
        for i, label in enumerate(["legitimate", "legitimate", "unknown", "abusive"])
    ]
    result = simulate(policy, rows)
    assert result["affected_count"] == 3
    assert result["false_positive_rate"] == 0.5
    assert result["affected_labels"] == {"legitimate": 1, "unknown": 1, "abusive": 1}


def test_regression_contracts():
    route = RouteContract(method="get", path="/items", authenticated=True, tenant_isolation=True)
    assert regressions([route], [route]) == []
    weakened = route.model_copy(update={"authenticated": False})
    assert regressions([route], [weakened])[0]["reason"] == "weakened"
    assert regressions([], [weakened])[0]["reason"] == "new_unprotected_route"
    with pytest.raises(ValueError):
        regressions([route, route], [route])


def test_llm_unavailable_falls_back(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "post", fail)
    result = explain({"findings": [{"reason": "cross_tenant_access"}]}, "http://localhost", "test")
    assert result["source"] == "deterministic" and result["model_error"]


def test_llm_receives_only_enumerated_counts(monkeypatch):
    def respond(self, url, **kwargs):
        import json

        payload = json.dumps(kwargs["json"])
        assert "secret-user" not in payload and "company-secret" not in payload
        return httpx.Response(
            200,
            json={"message": {"content": "Resumo limitado às evidências."}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", respond)
    result = explain(
        {
            "findings": [
                {
                    "reason": "cross_tenant_access",
                    "subject": "secret-user",
                    "actor_tenant": "company-secret",
                }
            ]
        },
        "http://localhost",
        "test",
    )
    assert result["source"] == "ollama" and result["advisory_only"]


def test_sdk_fails_closed_on_unavailable_or_malformed_response(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "post", fail)
    with SentinelClient("http://localhost", "fake") as client:
        with pytest.raises(SentinelUnavailable):
            client.decide(evt())


def test_reproducible_demo():
    result = run_demo()
    assert result["cross_company_denied"] and result["same_company_allowed"]
