import asyncio
from datetime import timedelta

import pytest
from test_administration import Model
from test_continuity import continuity as continuity

from qinzora.administration.contracts import Authority
from qinzora.administration.controller import Administrator
from qinzora.administration.monitor import Monitor
from qinzora.continuity.contracts import FallbackProfile, OperationContract
from qinzora.continuity.runtime import (
    CachedResponse,
    ContinuityRuntime,
    DependencyUnavailable,
    VerifiedCall,
)
from qinzora.continuity.service import create_contract, create_profile, set_rehearsal
from qinzora.errors import ApplicationError
from qinzora.models import now


def administrator(continuity, operations, **changes):
    repository, _, _, profile, _ = continuity
    authority = Authority(
        routes=[{"service": "shipping", "route": "/shipping"}],
        allow_stage=False,
        allow_enforce=False,
        continuity_profile_ids=[profile],
        objective="Keep shipping estimates available without caching checkout writes",
        **changes,
    )
    model = Model(operations)
    return Administrator(repository, model, authority), model


def test_ai_plan_activates_a_rehearsed_fallback_used_by_runtime(continuity):
    repository, read, _, profile, _ = continuity
    controller, model = administrator(
        continuity, [{"action": "activate_continuity", "profile_id": profile}]
    )
    plan = asyncio.run(controller.propose())
    context = model.context["continuity_profiles"][0]
    assert context["rehearsal_report"]["eligible"] and context["evidence_fresh"]
    assert "scenarios" not in context
    result = controller.execute(plan["id"])
    assert result["results"][0]["continuity_state"]["state"] == "active"

    async def offline():
        raise DependencyUnavailable()

    async def cached(*args):
        return CachedResponse({"amount": 10, "currency": "BRL"}, now(), "storefront", "a")

    response = asyncio.run(
        ContinuityRuntime(repository, {"local_estimates": cached}).run(
            read, VerifiedCall("storefront", "a", "a", True), offline
        )
    )
    assert response.source == "cache" and response.profile_id == profile
    assert controller.execute(plan["id"])["duplicate"]


def test_unregistered_profile_or_missing_grant_is_rejected(continuity):
    controller, _ = administrator(
        continuity, [{"action": "activate_continuity", "profile_id": "other"}]
    )
    with pytest.raises(ApplicationError, match="authority"):
        asyncio.run(controller.propose())


def test_replacing_evidence_after_proposal_requires_a_new_plan(continuity):
    repository, _, _, profile, suite = continuity
    controller, _ = administrator(
        continuity, [{"action": "activate_continuity", "profile_id": profile}]
    )
    plan = asyncio.run(controller.propose())
    suite.captured_at = now() - timedelta(seconds=2)
    with repository() as repo:
        set_rehearsal(repo, profile, suite)
    with pytest.raises(ApplicationError, match="evidence changed"):
        controller.execute(plan["id"])


def test_bad_continuity_impact_rolls_back_other_actions_in_the_plan(continuity):
    repository, _, _, profile, suite = continuity
    suite.scenarios[2].expected = "permit"
    with repository() as repo:
        set_rehearsal(repo, profile, suite)
    authority = Authority(
        routes=[{"service": "shipping", "route": "/shipping"}], continuity_profile_ids=[profile]
    )
    model = Model(
        [
            {
                "action": "stage_policy",
                "policy": {
                    "name": "observe",
                    "service": "shipping",
                    "route": "/shipping",
                    "kind": "tenant_isolation",
                },
            },
            {"action": "activate_continuity", "profile_id": profile},
        ]
    )
    controller = Administrator(repository, model, authority)
    plan = asyncio.run(controller.propose())
    with pytest.raises(ApplicationError, match="expectations"):
        controller.execute(plan["id"])
    with repository() as repo:
        assert not repo.policies()


def test_monitor_does_not_reinfer_due_to_its_own_continuity_activation(continuity, tenant):
    _, _, _, profile, _ = continuity
    controller, _ = administrator(
        continuity, [{"action": "activate_continuity", "profile_id": profile}]
    )

    async def run():
        monitor = Monitor(controller, tenant["id"], execute=True)
        assert (await monitor.tick())["status"] == "executed"
        assert (await monitor.tick())["status"] == "unchanged"

    asyncio.run(run())


def test_profile_cannot_reference_contracts_outside_its_service(continuity):
    repository, _, _, _, _ = continuity
    with repository() as repo:
        other = create_contract(
            repo, OperationContract(service="other", route="/r", consumer="c", effect="read")
        )["id"]
        with pytest.raises(ApplicationError, match="match its service"):
            create_profile(
                repo,
                FallbackProfile(
                    name="bad",
                    service="shipping",
                    route="/shipping",
                    source="estimates",
                    contract_ids=[other],
                ),
            )


def test_health_updates_during_inference_allow_plan_but_trigger_next_monitor_cycle(
    continuity, tenant
):
    repository, read, _, profile, _ = continuity
    controller, _ = administrator(
        continuity, [{"action": "activate_continuity", "profile_id": profile}]
    )

    class HealthChangingModel(Model):
        calls = 0

        async def generate(self, *args):
            self.calls += 1
            if self.calls == 1:
                with repository() as repo:
                    repo.put(
                        "continuity_health",
                        {"status": "unavailable", "failures": 1},
                        "continuity-health:" + read,
                    )
            return await super().generate(*args)

    model = HealthChangingModel([{"action": "activate_continuity", "profile_id": profile}])
    controller.model = model

    async def run():
        monitor = Monitor(controller, tenant["id"], execute=True)
        assert (await monitor.tick())["status"] == "executed"
        # The first proposal did not observe the new health signal. It must not
        # be swallowed by the executor's own activation checkpoint update.
        await monitor.tick()
        assert model.calls == 2
        assert (await monitor.tick())["status"] == "unchanged"

    asyncio.run(run())
