from datetime import timedelta

import httpx
import pytest
from conftest import auth
from test_api import policy, post_event

from qinzora.engine import simulate
from qinzora.lab import ProcessServer
from qinzora.live_demo import free_port
from qinzora.models import Event, Policy, now


def test_readiness_failure_does_not_leave_a_demo_process(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("readiness probe failed")

    server = ProcessServer(
        "qinzora",
        {
            "db": str(tmp_path / "demo.sqlite"),
            "admin": "x" * 32,
            "port": free_port(),
        },
    )
    monkeypatch.setattr(httpx.Client, "get", unavailable)
    with pytest.raises(httpx.ConnectError, match="readiness probe failed"):
        with server:
            pytest.fail("Failed readiness must not enter the body")
    assert server.process.pid is not None
    assert not server.process.is_alive()
    assert server.process.exitcode == 0


@pytest.mark.parametrize("naive", [False, True])
def test_replay_refuses_clock_histories_it_cannot_evaluate(naive):
    stamp = now()
    if naive:
        stamp = stamp.replace(tzinfo=None)
    rows = [
        {"at": stamp, "event": Event(service="s", route="/r", subject="u")},
        {"at": stamp - timedelta(seconds=1), "event": Event(service="s", route="/r", subject="u")},
    ]
    with pytest.raises(ValueError, match="Replay"):
        simulate(Policy(name="rate", service="s", kind="rate_limit"), rows)


def test_inconsistent_clock_cannot_produce_an_activation_report(api, tenant, event):
    client, _ = api
    pid = policy(client, tenant)
    post_event(client, tenant, event)
    post_event(client, tenant, {**event, "event_id": "later"})
    with client.app.state.store.transaction() as db:
        db.execute(
            "UPDATE events SET received=? WHERE event_id='later'",
            ((now() - timedelta(days=1)).isoformat(),),
        )
    response = client.post(f"/v1/policies/{pid}/simulate", headers=auth(tenant["manager_key"]))
    assert response.status_code == 409
    with client.app.state.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='simulation'").fetchone()[0] == 0


def test_clock_rollback_cannot_bypass_live_window(api, tenant, event, monkeypatch):
    client, _ = api
    policy(client, tenant, kind="rate_limit", threshold=1)
    timestamp = now()
    monkeypatch.setattr("qinzora.service.now", lambda: timestamp)
    first = post_event(client, tenant, event, "decisions")
    assert first.status_code == 200
    monkeypatch.setattr("qinzora.service.now", lambda: timestamp - timedelta(seconds=1))
    # A retry with the original id still returns its original decision.
    assert post_event(client, tenant, event, "decisions").json()["duplicate"]
    second = post_event(client, tenant, {**event, "event_id": "new"}, "decisions")
    assert second.status_code == 409
    with client.app.state.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
