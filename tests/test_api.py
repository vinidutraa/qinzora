import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import auth

from qinzora.models import now
from qinzora.store import Store


def policy(client, tenant, kind="tenant_isolation", **kwargs):
    response = client.post(
        "/v1/policies",
        headers=auth(tenant["manager_key"]),
        json={"name": "test", "service": "documents", "kind": kind, **kwargs},
    )
    assert response.status_code == 201
    return response.json()["id"]


def post_event(client, tenant, event, mode="events"):
    return client.post(f"/v1/{mode}", headers=auth(tenant["collector_key"]), json=event)


def simulation(client, tenant, pid):
    response = client.post(f"/v1/policies/{pid}/simulate", headers=auth(tenant["manager_key"]))
    assert response.status_code == 200
    return response.json()


def activate(client, tenant, pid, sid, acknowledge=True):
    return client.post(
        f"/v1/policies/{pid}/activate",
        headers=auth(tenant["manager_key"]),
        json={"simulation_id": sid, "acknowledge_impact": acknowledge},
    )


def test_auth_health_and_no_default_admin(api):
    client, _ = api
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/v1/policies").status_code == 401
    assert client.get("/v1/policies", headers=auth("wrong")).status_code == 401
    from qinzora.app import create_app

    with pytest.raises(ValueError):
        create_app(admin_token="short")


def test_collector_cannot_manage(api, tenant):
    client, _ = api
    assert client.get("/v1/policies", headers=auth(tenant["collector_key"])).status_code == 403
    assert (
        client.post(
            "/v1/admin/tenants", headers=auth(tenant["manager_key"]), json={"name": "bad"}
        ).status_code
        == 401
    )


def test_full_observe_replay_activate_revoke(api, tenant, event):
    client, _ = api
    pid = policy(client, tenant)
    cross = {**event, "resource_tenant": "company-b", "expected": "abusive"}
    first = post_event(client, tenant, cross).json()
    assert first["allowed"] and first["findings"][0]["reason"] == "cross_tenant_access"
    report = simulation(client, tenant, pid)
    assert report["affected_count"] == 1 and report["false_positive_rate"] is None
    assert activate(client, tenant, pid, report["id"], False).status_code == 409
    assert activate(client, tenant, pid, report["id"]).status_code == 200
    assert not post_event(client, tenant, {**cross, "event_id": "blocked"}, "decisions").json()[
        "allowed"
    ]
    assert post_event(client, tenant, {**event, "event_id": "allowed"}, "decisions").json()[
        "allowed"
    ]
    client.post(f"/v1/policies/{pid}/revoke", headers=auth(tenant["manager_key"]))
    assert post_event(client, tenant, {**cross, "event_id": "revoked"}, "decisions").json()[
        "allowed"
    ]
    actions = client.get("/v1/audit", headers=auth(tenant["manager_key"])).json()
    assert {"policy.activated", "policy.revoked"} <= {x["action"] for x in actions}


def test_cross_customer_objects_inaccessible(api, tenant, event):
    client, admin = api
    other = client.post("/v1/admin/tenants", headers=auth(admin), json={"name": "Other"}).json()
    pid = policy(client, tenant)
    post_event(client, tenant, event)
    report = simulation(client, tenant, pid)
    assert (
        client.post(f"/v1/policies/{pid}/simulate", headers=auth(other["manager_key"])).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/simulations/{report['id']}", headers=auth(other["manager_key"])
        ).status_code
        == 404
    )
    assert client.get("/v1/events", headers=auth(other["manager_key"])).json()["items"] == []
    assert client.get("/v1/incidents", headers=auth(other["manager_key"])).json() == []


def test_no_activation_without_evidence_or_matching_simulation(api, tenant, event):
    client, _ = api
    first = policy(client, tenant)
    empty = simulation(client, tenant, first)
    assert activate(client, tenant, first, empty["id"]).status_code == 409
    post_event(client, tenant, event)
    second = policy(client, tenant)
    report = simulation(client, tenant, first)
    assert activate(client, tenant, second, report["id"]).status_code == 409


def test_duplicate_is_idempotent_and_different_payload_conflicts(api, tenant, event):
    client, _ = api
    assert post_event(client, tenant, event).status_code == 201
    assert post_event(client, tenant, event).json()["duplicate"]
    assert post_event(client, tenant, {**event, "subject": "changed"}).status_code == 409
    assert post_event(client, tenant, event, "decisions").status_code == 409
    assert (
        client.get("/v1/usage", headers=auth(tenant["manager_key"])).json()["retained_events"] == 1
    )


def test_capacity_and_suspension(api, event):
    client, admin = api
    tenant = client.post(
        "/v1/admin/tenants", headers=auth(admin), json={"name": "Small", "event_limit": 1}
    ).json()
    post_event(client, tenant, event)
    assert post_event(client, tenant, {**event, "event_id": "overflow"}).status_code == 429
    assert (
        client.patch(
            f"/v1/admin/tenants/{tenant['id']}", headers=auth(admin), json={"enabled": False}
        ).status_code
        == 200
    )
    assert post_event(client, tenant, event).status_code == 403


@pytest.mark.parametrize(
    "extra",
    [
        {"password": "secret-must-not-echo"},
        {"route": "/x?token=secret-must-not-echo"},
        {"latency_ms": -1},
        {"actor_tenant": ""},
    ],
)
def test_invalid_input_does_not_echo_body(api, tenant, event, extra):
    client, _ = api
    response = post_event(client, tenant, {**event, **extra})
    assert response.status_code == 422
    assert "secret-must-not-echo" not in response.text


def test_body_limit(api, tenant):
    client, _ = api
    response = client.post(
        "/v1/events", headers=auth(tenant["collector_key"]), content=b"x" * (1048576 + 1)
    )
    assert response.status_code == 413


def test_key_rotation_invalidates_old_key(api, tenant, event):
    client, _ = api
    new_key = client.post(
        "/v1/keys/rotate?role=collector", headers=auth(tenant["manager_key"])
    ).json()["key"]
    assert post_event(client, tenant, event).status_code == 401
    assert post_event(client, {**tenant, "collector_key": new_key}, event).status_code == 201
    with client.app.state.store.transaction() as db:
        persisted = [r[0] for r in db.execute("SELECT digest FROM keys")]
    assert new_key not in persisted and all(len(x) == 64 for x in persisted)


def test_expired_simulation_and_expired_policy(api, tenant, event):
    client, _ = api
    pid = policy(client, tenant)
    post_event(client, tenant, event)
    report = simulation(client, tenant, pid)
    with client.app.state.store.transaction() as db:
        saved = Store.get(db, tenant["id"], "simulation", report["id"])
        saved["created_at"] = (now() - timedelta(minutes=16)).isoformat()
        Store.put(db, tenant["id"], "simulation", saved, report["id"])
    assert activate(client, tenant, pid, report["id"]).status_code == 409
    report = simulation(client, tenant, pid)
    assert activate(client, tenant, pid, report["id"]).status_code == 200
    with client.app.state.store.transaction() as db:
        saved = Store.get(db, tenant["id"], "policy", pid)
        saved["expires_at"] = (now() - timedelta(seconds=1)).isoformat()
        Store.put(db, tenant["id"], "policy", saved, pid)
    assert post_event(
        client, tenant, {**event, "event_id": "expired", "resource_tenant": "b"}, "decisions"
    ).json()["allowed"]


def test_rate_window_concurrent_requests_are_atomic(api, tenant, event):
    client, _ = api
    pid = policy(client, tenant, "rate_limit", threshold=3)
    post_event(client, tenant, {**event, "subject": "warmup"})
    report = simulation(client, tenant, pid)
    activate(client, tenant, pid, report["id"])

    def send(index):
        return post_event(
            client, tenant, {**event, "event_id": f"concurrent-{index}"}, "decisions"
        ).json()["allowed"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(12)))
    assert sum(results) == 3


def test_persistence_across_restart(api, tenant, event):
    client, token = api
    post_event(client, tenant, event)
    from fastapi.testclient import TestClient

    from qinzora.app import create_app

    with TestClient(create_app(client.app.state.store.path, token)) as restarted:
        result = restarted.get("/v1/events", headers=auth(tenant["manager_key"])).json()
        assert result["items"][0]["event"]["event_id"] == event["event_id"]


def test_control_api_rate_limit(api, tenant):
    client, _ = api
    import time

    from qinzora.service import digest

    with client.app.state.store.transaction() as db:
        db.execute(
            "INSERT INTO request_limits VALUES (?,?,600)",
            (digest(tenant["collector_key"]), int(time.time() // 60)),
        )
    response = client.post("/v1/events", json={}, headers=auth(tenant["collector_key"]))
    assert response.status_code == 429


def test_explanation_fallback_and_scope(api, tenant, event):
    client, admin = api
    policy(client, tenant)
    post_event(client, tenant, {**event, "resource_tenant": "b"})
    incident = client.get("/v1/incidents", headers=auth(tenant["manager_key"])).json()[0]
    explained = client.post(
        f"/v1/incidents/{incident['id']}/explain", headers=auth(tenant["manager_key"])
    ).json()
    assert explained["source"] == "deterministic" and explained["advisory_only"]
    assert "user-a" not in json.dumps(explained)
    other = client.post("/v1/admin/tenants", headers=auth(admin), json={"name": "Other"}).json()
    assert (
        client.post(
            f"/v1/incidents/{incident['id']}/explain", headers=auth(other["manager_key"])
        ).status_code
        == 404
    )
