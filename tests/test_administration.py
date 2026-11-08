import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta

import pytest
from conftest import auth
from test_api import post_event

from qinzora.administration.contracts import Authority, PlanProposal
from qinzora.administration.controller import Administrator
from qinzora.errors import ApplicationError
from qinzora.models import Policy, now
from qinzora.repository import account_transaction
from qinzora.service import create_policy


class Model:
    def __init__(self, operations):
        self.operations = operations
        self.context = None

    async def generate(self, system, context, result_type):
        self.context = context
        return result_type.model_validate(
            {"rationale": "Respond to observed evidence", "operations": self.operations}
        )


def operation(action="enforce_policy", **changes):
    return {
        "action": action,
        "policy": {
            "name": "tenant safety",
            "service": "documents",
            "route": "/documents/{id}",
            "kind": "tenant_isolation",
            "ttl_seconds": 60,
            **changes,
        },
    }


@pytest.fixture
def setup(api, tenant, event):
    client, _ = api

    @contextmanager
    def repository():
        with account_transaction(client.app.state.store, tenant["id"]) as repo:
            yield repo

    post_event(client, tenant, {**event, "expected": "legitimate"})
    post_event(
        client,
        tenant,
        {**event, "event_id": "abusive", "resource_tenant": "other", "expected": "abusive"},
    )
    authority = Authority(
        routes=[{"service": "documents", "route": "/documents/{id}"}], allow_enforce=True
    )
    return repository, authority


def draft(repository, authority, operations):
    model = Model(operations)
    administrator = Administrator(repository, model, authority)
    plan = asyncio.run(administrator.propose())
    return administrator, model, plan


def test_model_plan_simulates_enforces_and_is_idempotent(api, tenant, event, setup):
    repository, authority = setup
    administrator, model, plan = draft(repository, authority, [operation()])
    assert plan["state"] == "draft"
    context = json.dumps(model.context)
    assert event["subject"] not in context
    assert event["actor_tenant"] not in context
    assert tenant["collector_key"] not in context
    assert model.context["summaries"][0]["counts"]["cross_tenant_attempts"] == 1
    result = administrator.execute(plan["id"])
    assert result["state"] == "executed" and not result["duplicate"]
    assert administrator.execute(plan["id"])["duplicate"]
    client, _ = api
    response = post_event(
        client,
        tenant,
        {**event, "event_id": "after-agent", "resource_tenant": "other"},
        "decisions",
    )
    assert response.status_code == 200 and not response.json()["allowed"]
    with repository() as repo:
        assert len(repo.policies()) == 1
        assert repo.get("simulation", result["results"][0]["simulation_id"])["affected_count"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"service": "outside"},
        {"route": "*"},
        {"ttl_seconds": 301},
        {"kind": "rate_limit", "threshold": 1},
        {"kind": "latency"},
    ],
)
def test_unauthorized_model_operations_cannot_be_saved(setup, change):
    repository, authority = setup
    with pytest.raises(ApplicationError):
        draft(repository, authority, [operation(**change)])
    with repository() as repo:
        assert not repo.policies()


def test_default_authority_cannot_enforce(setup):
    repository, _ = setup
    authority = Authority(routes=[{"service": "documents", "route": "*"}])
    with pytest.raises(ApplicationError, match="authority"):
        draft(repository, authority, [operation()])


def test_failure_in_second_action_rolls_back_the_entire_plan(setup):
    repository, authority = setup
    administrator, _, plan = draft(
        repository,
        authority,
        [
            operation("stage_policy"),
            operation(kind="rate_limit", threshold=10),  # no abusive sample exceeds the limit
        ],
    )
    with pytest.raises(ApplicationError, match="Simulation"):
        administrator.execute(plan["id"])
    with repository() as repo:
        assert not repo.policies()
        assert repo.get("administration_plan", plan["id"])["state"] == "draft"
        assert (
            repo.db.execute("SELECT count(*) FROM objects WHERE kind='simulation'").fetchone()[0]
            == 0
        )
        assert (
            repo.db.execute(
                "SELECT count(*) FROM objects WHERE kind='audit' "
                "AND json_extract(data,'$.action')='policy.created'"
            ).fetchone()[0]
            == 0
        )


def test_execution_replays_new_events_and_rejects_new_false_positives(api, tenant, event, setup):
    repository, authority = setup
    administrator, _, plan = draft(repository, authority, [operation()])
    post_event(
        api[0],
        tenant,
        {
            **event,
            "event_id": "legitimate-cross",
            "resource_tenant": "other",
            "expected": "legitimate",
        },
    )
    with pytest.raises(ApplicationError, match="Simulation"):
        administrator.execute(plan["id"])
    with repository() as repo:
        assert not repo.policies()


def test_stale_policy_inventory_cannot_be_executed(api, tenant, setup):
    repository, authority = setup
    administrator, _, plan = draft(repository, authority, [operation()])
    api[0].post("/v1/policies", headers=auth(tenant["manager_key"]), json=operation()["policy"])
    with pytest.raises(ApplicationError, match="inventory changed"):
        administrator.execute(plan["id"])


@pytest.mark.parametrize("offset", [timedelta(seconds=301), timedelta(seconds=-1)])
def test_expired_or_future_plan_cannot_be_executed(setup, offset, monkeypatch):
    repository, authority = setup
    administrator, _, plan = draft(repository, authority, [operation()])
    stamp = now()
    with repository() as repo:
        item = repo.get("administration_plan", plan["id"])
        item["context"]["created_at"] = (stamp - offset).isoformat()
        repo.put("administration_plan", item, plan["id"])
    monkeypatch.setattr("qinzora.administration.controller.now", lambda: stamp)
    with pytest.raises(ApplicationError, match="expired or clock changed"):
        administrator.execute(plan["id"])


def test_revocation_requires_explicit_grant_and_scope(setup):
    repository, authority = setup
    administrator, _, plan = draft(repository, authority, [operation()])
    policy_id = administrator.execute(plan["id"])["results"][0]["policy_id"]
    revoke = {"action": "revoke_policy", "policy_id": policy_id}
    with pytest.raises(ApplicationError, match="authority"):
        draft(repository, authority, [revoke])
    granted = authority.model_copy(update={"revocable_policy_ids": [policy_id]})
    administrator, _, plan = draft(repository, granted, [revoke])
    administrator.execute(plan["id"])
    with repository() as repo:
        assert repo.get("policy", policy_id)["state"] == "revoked"


def test_changing_grants_invalidates_a_plan(setup):
    repository, authority = setup
    _, _, plan = draft(repository, authority, [operation()])
    restricted = authority.model_copy(update={"allow_enforce": False})
    administrator = Administrator(repository, Model([]), restricted)
    with pytest.raises(ApplicationError, match="authority changed"):
        administrator.execute(plan["id"])


def test_model_cannot_mutate_the_saved_snapshot(setup):
    repository, authority = setup

    class MutatingModel:
        async def generate(self, system, context, result_type):
            context["policy_revision"] = "fake"
            context["authority"]["routes"] = []
            return PlanProposal(rationale="No changes needed", operations=[])

    administrator = Administrator(repository, MutatingModel(), authority)
    plan = asyncio.run(administrator.propose())
    assert plan["context"]["policy_revision"] != "fake"
    assert plan["context"]["authority"]["routes"]
    assert administrator.execute(plan["id"])["results"] == []


def test_concurrent_execution_performs_actions_once(setup):
    repository, authority = setup
    administrator, _, plan = draft(repository, authority, [operation()])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(administrator.execute, [plan["id"], plan["id"]]))
    assert sorted(row["duplicate"] for row in results) == [False, True]
    with repository() as repo:
        assert len(repo.policies()) == 1


def test_account_disabled_after_proposal_cannot_be_administered(api, tenant, setup):
    repository, authority = setup
    administrator, _, plan = draft(repository, authority, [operation()])
    api[0].patch(f"/v1/admin/tenants/{tenant['id']}", headers=auth(api[1]), json={"enabled": False})
    with pytest.raises(ApplicationError, match="Account is disabled"):
        administrator.execute(plan["id"])


def test_plans_are_not_accessible_from_another_account(api, setup):
    repository, authority = setup
    _, _, plan = draft(repository, authority, [operation()])
    other = api[0].post("/v1/admin/tenants", headers=auth(api[1]), json={"name": "Other"}).json()

    @contextmanager
    def other_repository():
        with account_transaction(api[0].app.state.store, other["id"]) as repo:
            yield repo

    administrator = Administrator(other_repository, Model([]), authority)
    with pytest.raises(ApplicationError, match="Not found"):
        administrator.execute(plan["id"])


def test_model_is_called_outside_the_write_transaction(setup):
    repository, authority = setup

    class ObservingModel:
        async def generate(self, system, context, result_type):
            # Opening another write transaction would time out if inference held the lock.
            with repository() as repo:
                repo.audit("test.model_running", {})
            return PlanProposal(rationale="No action", operations=[])

    assert (
        asyncio.run(Administrator(repository, ObservingModel(), authority).propose())["state"]
        == "draft"
    )


@pytest.mark.parametrize("expired", [False, True])
def test_enforcement_reuses_equivalent_candidates_or_expired_policies(setup, expired):
    repository, authority = setup
    with repository() as repo:
        old = create_policy(repo, Policy.model_validate(operation(ttl_seconds=900)["policy"]))
        if expired:
            item = repo.get("policy", old["id"])
            item.update(state="active", expires_at=(now() - timedelta(seconds=1)).isoformat())
            repo.put("policy", item, old["id"])
    administrator, _, plan = draft(repository, authority, [operation(ttl_seconds=60)])
    result = administrator.execute(plan["id"])
    assert result["results"][0]["policy_id"] == old["id"]
    with repository() as repo:
        assert len(repo.policies()) == 1
        item = repo.get("policy", old["id"])
        assert item["state"] == "active" and item["policy"]["ttl_seconds"] == 60
