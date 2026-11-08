import random
from datetime import timedelta

import pytest
from conftest import auth
from test_api import activate, policy, post_event, simulation

from qinzora.engine import evaluate, simulate
from qinzora.models import Event, Policy, now


@pytest.mark.parametrize("kind", ["rate_limit", "error_burst", "tenant_isolation", "latency"])
def test_replay_agrees_with_live_evaluation(kind):
    rng = random.Random(42)
    start = now()
    rows = []
    for index in range(250):
        rows.append(
            {
                "at": start + timedelta(seconds=index // 5),
                "event": Event(
                    event_id=str(index),
                    service=rng.choice(["svc", "other"]),
                    route=rng.choice(["/a", "/b"]),
                    subject=rng.choice(["u1", "u2"]),
                    actor_tenant="a",
                    resource_tenant=rng.choice(["a", "b", None]),
                    latency_ms=rng.randint(0, 100),
                    status_code=rng.choice([200, 401, 500]),
                ),
            }
        )
    candidate = Policy(name="contract", service="svc", kind=kind, threshold=3, window_seconds=10)
    reference = sum(
        evaluate(candidate, row["event"], row["at"], rows[:i]) is not None
        for i, row in enumerate(rows)
    )
    assert simulate(candidate, rows)["affected_count"] == reference


@pytest.mark.parametrize("kind", ["error_burst", "latency"])
def test_observation_only_policies_cannot_be_activated(api, tenant, event, kind):
    client, _ = api
    pid = policy(client, tenant, kind)
    post_event(client, tenant, event)
    report = simulation(client, tenant, pid)
    assert not report["activation_eligible"]
    assert activate(client, tenant, pid, report["id"]).status_code == 409


def test_export_cursor_preserves_all_events(api, tenant, event):
    client, _ = api
    for i in range(4):
        post_event(client, tenant, {**event, "event_id": str(i)})
    cursor, ids = 0, []
    for _ in range(5):
        batch = client.get(
            f"/v1/events?limit=1&after={cursor}", headers=auth(tenant["manager_key"])
        ).json()
        ids.extend(row["event"]["event_id"] for row in batch["items"])
        cursor = batch["next_cursor"]
    assert ids == ["0", "1", "2", "3"]
