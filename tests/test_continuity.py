import asyncio
from datetime import timedelta
from functools import partial

import pytest

from qinzora.continuity.contracts import FallbackProfile, OperationContract, Rehearsal
from qinzora.continuity.engine import evaluate_rules
from qinzora.continuity.runtime import (
    CachedResponse,
    ContinuityRuntime,
    ContinuityUnavailable,
    DependencyUnavailable,
    VerifiedCall,
)
from qinzora.continuity.service import (
    activate_profile,
    create_contract,
    create_profile,
    inspect_profile,
    revoke_profile,
    set_rehearsal,
)
from qinzora.errors import ApplicationError
from qinzora.models import now
from qinzora.repository import account_transaction


@pytest.fixture
def continuity(api, tenant):
    repository = partial(account_transaction, api[0].app.state.store, tenant["id"])
    with repository() as repo:
        read = create_contract(
            repo,
            OperationContract(
                service="shipping",
                route="/shipping",
                consumer="storefront",
                effect="read",
                allow_cached=True,
                maximum_age_seconds=900,
                required_fields=["amount", "currency"],
            ),
        )["id"]
        write = create_contract(
            repo,
            OperationContract(
                service="shipping",
                route="/shipping",
                consumer="checkout",
                effect="write",
                required_fields=["amount", "currency"],
            ),
        )["id"]
        profile = create_profile(
            repo,
            FallbackProfile(
                name="estimate continuity",
                service="shipping",
                route="/shipping",
                source="local_estimates",
                contract_ids=[read, write],
                ttl_seconds=60,
            ),
        )["id"]
        observed = {
            "available": True,
            "age_seconds": 120,
            "fields": ["amount", "currency"],
            "authorized": True,
            "same_tenant": True,
            "consumer_matches": True,
        }
        suite = Rehearsal.model_validate(
            {
                "captured_at": now(),
                "scenarios": [
                    {
                        "name": "fresh estimate",
                        "contract_id": read,
                        "observed": observed,
                        "expected": "permit",
                    },
                    {
                        "name": "stale estimate",
                        "contract_id": read,
                        "observed": {**observed, "age_seconds": 901},
                        "expected": "deny",
                    },
                    {
                        "name": "checkout cannot use cache",
                        "contract_id": write,
                        "observed": {**observed, "age_seconds": 0},
                        "expected": "deny",
                    },
                    {
                        "name": "cross tenant",
                        "contract_id": read,
                        "observed": {**observed, "same_tenant": False},
                        "expected": "deny",
                    },
                ],
            }
        )
        set_rehearsal(repo, profile, suite)
    return repository, read, write, profile, suite


def enable(continuity):
    repository, _, _, profile, _ = continuity
    with repository() as repo:
        return activate_profile(repo, profile, maximum_ttl=60, maximum_evidence_age=900)


async def outage():
    raise DependencyUnavailable("dependency offline")


def test_rehearsal_distinguishes_estimates_staleness_writes_and_tenants(continuity):
    repository, _, _, profile, _ = continuity
    with repository() as repo:
        report = inspect_profile(repo, profile)["report"]
    assert report["eligible"]
    assert [case["decision"] for case in report["cases"]] == ["permit", "deny", "deny", "deny"]
    assert "snapshot_too_old" in report["cases"][1]["reasons"]
    assert "cached_response_not_permitted" in report["cases"][2]["reasons"]


def test_actual_fallback_recovers_to_primary_when_dependency_returns(continuity):
    repository, read, _, profile, _ = continuity
    enable(continuity)

    async def load(contract_id, call):
        assert contract_id == read and call.actor_tenant == "company-a"
        return CachedResponse(
            {"amount": 12, "currency": "BRL"},
            now() - timedelta(seconds=120),
            "storefront",
            "company-a",
        )

    async def healthy():
        return {"amount": 14, "currency": "BRL"}

    async def run():
        runtime = ContinuityRuntime(repository, {"local_estimates": load})
        call = VerifiedCall("storefront", "company-a", "company-a", True)
        fallback = await runtime.run(read, call, outage)
        assert fallback.source == "cache" and fallback.data["amount"] == 12
        assert fallback.profile_id == profile
        restored = await runtime.run(read, call, healthy)
        assert restored.source == "primary" and restored.data["amount"] == 14

    asyncio.run(run())


def test_write_failure_never_calls_cache_or_repeats_the_operation(continuity):
    repository, _, write, _, _ = continuity
    enable(continuity)
    committed = []

    async def uncertain_write():
        committed.append("purchase")
        raise DependencyUnavailable("response failed after commit")

    async def forbidden_loader(*args):
        pytest.fail("A write must not be retried or replaced with a cached response")

    runtime = ContinuityRuntime(repository, {"local_estimates": forbidden_loader})
    with pytest.raises(ContinuityUnavailable) as failure:
        asyncio.run(runtime.run(write, VerifiedCall("checkout", "a", "a", True), uncertain_write))
    assert failure.value.reasons == ["cached_response_not_permitted"]
    assert committed == ["purchase"]


@pytest.mark.parametrize(
    "call",
    [
        VerifiedCall("storefront", "a", "a"),
        VerifiedCall("storefront", "a", "b", True),
        VerifiedCall("wrong", "a", "a", True),
    ],
)
def test_unverified_identity_never_reaches_primary_or_cache(continuity, call):
    repository, read, _, _, _ = continuity

    async def forbidden(*args):
        pytest.fail("Unauthorized calls must stop before executing adapters")

    with pytest.raises(ContinuityUnavailable):
        asyncio.run(
            ContinuityRuntime(repository, {"local_estimates": forbidden}).run(read, call, forbidden)
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"generated_at": lambda: now() - timedelta(seconds=901)}, "snapshot_too_old"),
        ({"generated_at": lambda: now() + timedelta(seconds=30)}, "snapshot_clock_invalid"),
        ({"generated_at": lambda: now().replace(tzinfo=None)}, "snapshot_clock_invalid"),
        ({"resource_tenant": "other"}, "tenant_scope_mismatch"),
        ({"consumer": "other"}, "consumer_mismatch"),
        ({"data": {"amount": 1}}, "required_fields_missing"),
    ],
)
def test_live_data_is_checked_again_after_successful_rehearsal(continuity, change, reason):
    repository, read, _, _, _ = continuity
    enable(continuity)

    async def load(*args):
        values = {
            "data": {"amount": 1, "currency": "BRL"},
            "generated_at": now(),
            "resource_tenant": "a",
            "consumer": "storefront",
        }
        values.update({key: value() if callable(value) else value for key, value in change.items()})
        return CachedResponse(**values)

    with pytest.raises(ContinuityUnavailable) as failure:
        asyncio.run(
            ContinuityRuntime(repository, {"local_estimates": load}).run(
                read, VerifiedCall("storefront", "a", "a", True), outage
            )
        )
    assert reason in failure.value.reasons


def test_revocation_while_loading_cache_prevents_returning_its_payload(continuity):
    repository, read, _, profile, _ = continuity
    enable(continuity)

    async def load(*args):
        with repository() as repo:
            revoke_profile(repo, profile)
        return CachedResponse({"amount": 1, "currency": "BRL"}, now(), "storefront", "a")

    with pytest.raises(ContinuityUnavailable):
        asyncio.run(
            ContinuityRuntime(repository, {"local_estimates": load}).run(
                read, VerifiedCall("storefront", "a", "a", True), outage
            )
        )


def test_changed_or_bad_rehearsal_cannot_stay_active(continuity):
    repository, _, _, profile, suite = continuity
    enable(continuity)
    bad = suite.model_copy(deep=True)
    bad.scenarios[2].expected = "permit"
    with repository() as repo:
        set_rehearsal(repo, profile, bad)
    with pytest.raises(ApplicationError, match="expectations"):
        enable(continuity)
    with repository() as repo:
        assert inspect_profile(repo, profile)["state"] == "candidate"


def test_old_rehearsal_cannot_authorize_activation(continuity):
    repository, _, _, profile, suite = continuity
    suite.captured_at = now() - timedelta(hours=1)
    with repository() as repo:
        set_rehearsal(repo, profile, suite)
    with pytest.raises(ApplicationError, match="expired"):
        enable(continuity)


@pytest.mark.parametrize(
    "expected,actual,passed",
    [
        (True, 1, False),
        (1, True, False),
        ("1", 1, False),
        (1, 1.0, True),
        ("BRL", "USD", False),
        ("BRL", "BRL", True),
    ],
)
def test_value_rules_do_not_confuse_boolean_numeric_or_string_values(expected, actual, passed):
    contract = OperationContract(
        service="s",
        route="/r",
        consumer="c",
        effect="read",
        value_rules=[{"name": "rule", "field": "value", "expected": expected}],
    )
    assert evaluate_rules(contract, {"value": actual}) == {"rule": passed}


def test_caller_cancellation_does_not_start_a_fallback(continuity):
    repository, read, _, _, _ = continuity
    enable(continuity)

    async def cancelled():
        raise asyncio.CancelledError()

    async def forbidden(*args):
        pytest.fail("Cancellation must propagate without starting fallback work")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            ContinuityRuntime(repository, {"local_estimates": forbidden}).run(
                read, VerifiedCall("storefront", "a", "a", True), cancelled
            )
        )
