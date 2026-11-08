"""Exercise policy administration without a web server or SQLite adapter."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from qinzora.errors import ApplicationError
from qinzora.models import Activation, Event, Policy, now
from qinzora.service import (
    activate_policy,
    create_policy,
    record,
    revoke_policy,
    run_simulation,
)


class MemoryRepository:
    """Single-threaded test adapter; deliberately no database connection."""

    def __init__(self):
        self.objects = {}
        self.events = []
        self.actions = []

    def previous_event(self, event_id):
        return next(
            (
                (r["event"], deepcopy(r["result"]))
                for r in self.events
                if r["event"].event_id == event_id
            ),
            None,
        )

    def event_count(self):
        return len(self.events)

    def event_limit(self):
        return 100

    def latest_timestamp(self):
        return self.events[-1]["at"] if self.events else None

    def policies(self):
        return [
            {"id": key, **deepcopy(value)}
            for (kind, key), value in self.objects.items()
            if kind == "policy"
        ]

    def counts(self, event, start, end):
        rows = [
            r
            for r in self.events
            if start < r["at"] <= end
            and (r["event"].service, r["event"].route, r["event"].subject)
            == (event.service, event.route, event.subject)
        ]
        return len(rows), sum(r["event"].status_code >= 400 for r in rows)

    def append_event(self, event, timestamp, result):
        self.events.append(
            {
                "event": event.model_copy(deep=True),
                "at": timestamp,
                "result": deepcopy(result),
                "seq": len(self.events) + 1,
            }
        )

    def snapshot(self):
        return deepcopy(self.events)

    def get(self, kind, object_id):
        return deepcopy(self.objects.get((kind, object_id)))

    def put(self, kind, data, object_id=None):
        object_id = object_id or str(uuid4())
        self.objects[kind, object_id] = deepcopy(data)
        return object_id

    def audit(self, action, detail):
        self.actions.append((action, deepcopy(detail)))


def test_entire_policy_lifecycle_without_http_or_sqlite():
    repository = MemoryRepository()
    policy = create_policy(repository, Policy(name="isolate", service="s", kind="tenant_isolation"))
    event = Event(service="s", route="/r", subject="u", actor_tenant="a", resource_tenant="b")
    assert record(repository, event, enforce=False)["allowed"]
    simulation = run_simulation(repository, policy["id"])
    assert simulation["affected_count"] == 1
    with pytest.raises(ApplicationError, match="acknowledge"):
        activate_policy(repository, policy["id"], Activation(simulation_id=simulation["id"]))
    assert repository.get("policy", policy["id"])["state"] == "candidate"
    activate_policy(
        repository,
        policy["id"],
        Activation(simulation_id=simulation["id"], acknowledge_impact=True),
    )
    assert not record(repository, event.model_copy(update={"event_id": "blocked"}), True)["allowed"]
    revoke_policy(repository, policy["id"])
    assert record(repository, event.model_copy(update={"event_id": "revoked"}), True)["allowed"]
    assert [action for action, _ in repository.actions] == [
        "policy.created",
        "simulation.created",
        "policy.activated",
        "policy.revoked",
    ]


@pytest.mark.parametrize("offset", [timedelta(minutes=16), timedelta(minutes=-1)])
def test_activation_rejects_stale_or_future_report(offset, monkeypatch):
    repository = MemoryRepository()
    policy = create_policy(repository, Policy(name="isolate", service="s", kind="tenant_isolation"))
    record(repository, Event(service="s", route="/r", subject="u"), False)
    simulation = run_simulation(repository, policy["id"])
    stamp = now()
    simulation["created_at"] = (stamp - offset).isoformat()
    repository.put("simulation", simulation, simulation["id"])
    monkeypatch.setattr("qinzora.service.now", lambda: stamp)
    with pytest.raises(ApplicationError, match="clock changed"):
        activate_policy(
            repository,
            policy["id"],
            Activation(simulation_id=simulation["id"], acknowledge_impact=True),
        )
    assert repository.get("policy", policy["id"])["state"] == "candidate"
    assert "policy.activated" not in [action for action, _ in repository.actions]
