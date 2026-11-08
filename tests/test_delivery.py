import json

import httpx
import pytest

from qinzora.client import QinzoraClient, QinzoraUnavailable
from qinzora.live_demo import run_live_demo
from qinzora.models import Event
from qinzora.store import Store


def test_two_independent_processes_and_failure_recovery():
    result = run_live_demo()
    assert result["passed"]
    steps = {row["step"]: row for row in result["steps"]}
    assert steps["dependency_outage"]["status"] == 503
    assert not steps["dependency_outage"]["data_disclosed"]
    assert steps["restart_and_recovery"]["database_preserved"]


@pytest.mark.parametrize("payload", [[], None, "allow", {"allowed": "true"}, {}])
def test_sdk_rejects_malformed_decisions(monkeypatch, payload):
    def respond(self, url, **kwargs):
        return httpx.Response(
            200,
            content=json.dumps(payload),
            request=httpx.Request("POST", "http://localhost" + url),
        )

    monkeypatch.setattr(httpx.Client, "post", respond)
    with QinzoraClient("http://localhost", "fake") as client:
        with pytest.raises(QinzoraUnavailable):
            client.decide(Event(service="test", route="/test", subject="a"))


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_sdk_never_allows_on_remote_errors(monkeypatch, status):
    def respond(self, url, **kwargs):
        return httpx.Response(
            status,
            json={"detail": "error"},
            request=httpx.Request("POST", "http://localhost" + url),
        )

    monkeypatch.setattr(httpx.Client, "post", respond)
    with QinzoraClient("http://localhost", "fake") as client:
        with pytest.raises(QinzoraUnavailable):
            client.decide(Event(service="test", route="/test", subject="a"))


def test_sdk_times_out_without_implicit_allow(monkeypatch):
    def respond(*args, **kwargs):
        raise httpx.ReadTimeout("slow service")

    monkeypatch.setattr(httpx.Client, "post", respond)
    with QinzoraClient("http://localhost", "fake", timeout=0.1) as client:
        with pytest.raises(QinzoraUnavailable):
            client.decide(Event(service="test", route="/test", subject="a"))


def test_schema_migration_preserves_existing_response_status(tmp_path):
    store = Store(str(tmp_path / "legacy.sqlite"))
    store.initialize()
    event = Event(event_id="old", service="legacy", route="/test", subject="u", status_code=500)
    with store.transaction() as db:
        db.execute("ALTER TABLE events DROP COLUMN status_code")
        db.execute("UPDATE schema_version SET version=1")
        db.execute(
            "INSERT INTO events(tenant,event_id,received,service,route,subject,data,result) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                "t",
                "old",
                "2026-01-01T00:00:00+00:00",
                "legacy",
                "/test",
                "u",
                event.model_dump_json(),
                "{}",
            ),
        )
    store.initialize()
    with store.transaction() as db:
        assert db.execute("SELECT status_code FROM events").fetchone()[0] == 500
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 2


def test_usage_has_no_billing(api, tenant):
    from conftest import auth

    client, _ = api
    result = client.get("/v1/usage", headers=auth(tenant["manager_key"])).json()
    assert "billing" not in result


def test_sql_error_counters_match_response_events(api, tenant, event):
    from test_api import policy, post_event

    client, _ = api
    policy(client, tenant, "error_burst", threshold=2)
    first = post_event(client, tenant, {**event, "status_code": 500}).json()
    assert first["findings"] == []
    second = post_event(client, tenant, {**event, "event_id": "second", "status_code": 401}).json()
    assert second["findings"][0]["reason"] == "error_burst"
    assert second["allowed"]
