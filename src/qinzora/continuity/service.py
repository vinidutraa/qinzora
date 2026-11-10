"""Account-scoped configuration, rehearsal, activation and live binding checks."""

from datetime import datetime, timedelta

from ..errors import ApplicationError, require
from ..models import now
from ..ports import Repository
from ..serialization import fingerprint
from .contracts import FallbackProfile, OperationContract, Rehearsal
from .engine import simulate


def create_contract(repository: Repository, contract: OperationContract) -> dict:
    contract_id = repository.put("continuity_contract", contract.model_dump())
    repository.audit("continuity.contract_created", {"contract_id": contract_id})
    return {"id": contract_id, **contract.model_dump()}


def create_profile(repository: Repository, profile: FallbackProfile) -> dict:
    for contract_id in profile.contract_ids:
        contract = OperationContract.model_validate(
            require(repository.get("continuity_contract", contract_id))
        )
        if (contract.service, contract.route) != (profile.service, profile.route):
            raise ApplicationError("conflict", "Profile contracts must match its service and route")
    item = {
        "profile": profile.model_dump(),
        "state": "candidate",
        "expires_at": None,
        "rehearsal": None,
    }
    profile_id = repository.put("continuity_profile", item)
    repository.audit("continuity.profile_created", {"profile_id": profile_id})
    return {"id": profile_id, **item}


def set_rehearsal(repository: Repository, profile_id: str, rehearsal: Rehearsal) -> None:
    item = require(repository.get("continuity_profile", profile_id))
    profile = FallbackProfile.model_validate(item["profile"])
    contracts = {
        key: OperationContract.model_validate(require(repository.get("continuity_contract", key)))
        for key in profile.contract_ids
    }
    try:
        simulate(contracts, rehearsal)
    except ValueError as exc:
        raise ApplicationError(
            "conflict", "Rehearsal references contracts outside the profile"
        ) from exc
    if rehearsal.captured_at > now():
        raise ApplicationError("conflict", "Rehearsal cannot come from the future")
    # A changed rehearsal invalidates activation until the new evidence is checked.
    item.update(rehearsal=rehearsal.model_dump(mode="json"), state="candidate", expires_at=None)
    repository.put("continuity_profile", item, profile_id)
    repository.audit("continuity.rehearsal_updated", {"profile_id": profile_id})


def inspect_profile(repository: Repository, profile_id: str) -> dict:
    item = require(repository.get("continuity_profile", profile_id))
    profile = FallbackProfile.model_validate(item["profile"])
    contracts = {
        key: OperationContract.model_validate(require(repository.get("continuity_contract", key)))
        for key in profile.contract_ids
    }
    if item["rehearsal"] is None:
        report = {"eligible": False, "cases": [], "uncovered_contract_ids": profile.contract_ids}
    else:
        report = simulate(contracts, Rehearsal.model_validate(item["rehearsal"]))
    return {
        "id": profile_id,
        **item,
        "contracts": {key: contract.model_dump() for key, contract in contracts.items()},
        "report": report,
    }


def activation_digest(item: dict) -> str:
    return fingerprint({key: item[key] for key in ("profile", "contracts", "rehearsal")})


def binding_id(contract_id: str) -> str:
    return "continuity-binding:" + contract_id


def record_health(repository: Repository, contract_id: str, *, healthy: bool) -> None:
    signal_id = "continuity-health:" + contract_id
    signal = repository.get("continuity_health", signal_id)
    if healthy and (signal is None or signal["status"] == "healthy"):
        return
    signal = signal or {"failures": 0, "last_failure_at": None, "last_success_at": None}
    if healthy:
        signal.update(status="healthy", last_success_at=now().isoformat())
    else:
        signal.update(
            status="unavailable", failures=signal["failures"] + 1, last_failure_at=now().isoformat()
        )
    repository.put("continuity_health", signal, signal_id)
    repository.audit(
        "continuity.primary_recovered" if healthy else "continuity.primary_unavailable",
        {"contract_id": contract_id},
    )


def activate_profile(
    repository: Repository, profile_id: str, *, maximum_ttl: int, maximum_evidence_age: int
) -> dict:
    item = inspect_profile(repository, profile_id)
    profile = FallbackProfile.model_validate(item["profile"])
    if profile.ttl_seconds > maximum_ttl:
        raise ApplicationError("conflict", "Continuity TTL exceeds execution authority")
    if not item["report"]["eligible"]:
        raise ApplicationError("conflict", "Continuity rehearsal did not satisfy all expectations")
    rehearsal = Rehearsal.model_validate(item["rehearsal"])
    stamp = now()
    age = stamp - rehearsal.captured_at
    if age < timedelta(0) or age > timedelta(seconds=maximum_evidence_age):
        raise ApplicationError("conflict", "Continuity rehearsal expired or clock changed")
    item.update(
        state="active", expires_at=(stamp + timedelta(seconds=profile.ttl_seconds)).isoformat()
    )
    stored = {key: item[key] for key in ("profile", "state", "expires_at", "rehearsal")}
    repository.put("continuity_profile", stored, profile_id)
    signature = activation_digest(item)
    for contract_id in profile.contract_ids:
        repository.put(
            "continuity_binding",
            {"profile_id": profile_id, "digest": signature},
            binding_id(contract_id),
        )
    repository.audit(
        "continuity.activated",
        {"profile_id": profile_id, "digest": signature, "expires_at": item["expires_at"]},
    )
    return {"id": profile_id, **stored}


def revoke_profile(repository: Repository, profile_id: str) -> dict:
    item = require(repository.get("continuity_profile", profile_id))
    item.update(state="revoked", expires_at=None)
    repository.put("continuity_profile", item, profile_id)
    repository.audit("continuity.revoked", {"profile_id": profile_id})
    return {"id": profile_id, **item}


def resolve_profile(repository: Repository, contract_id: str) -> dict:
    binding = require(
        repository.get("continuity_binding", binding_id(contract_id)),
        "No continuity profile is active",
    )
    item = inspect_profile(repository, binding["profile_id"])
    if (
        contract_id not in item["profile"]["contract_ids"]
        or item["state"] != "active"
        or datetime.fromisoformat(item["expires_at"]) <= now()
        or binding["digest"] != activation_digest(item)
    ):
        raise ApplicationError("conflict", "Continuity binding expired or changed")
    return item


def profile_summary(repository: Repository, profile_id: str, maximum_evidence_age: int) -> dict:
    """Summarize rehearsal/configuration without exposing response payloads or identity values."""
    item = inspect_profile(repository, profile_id)
    stamp, active = now(), []
    signature = activation_digest(item)
    if item["state"] == "active" and datetime.fromisoformat(item["expires_at"]) > stamp:
        for contract_id in item["profile"]["contract_ids"]:
            binding = repository.get("continuity_binding", binding_id(contract_id))
            if binding and binding["profile_id"] == profile_id and binding["digest"] == signature:
                active.append(contract_id)
    captured = item["rehearsal"]["captured_at"] if item["rehearsal"] else None
    age = (stamp - datetime.fromisoformat(captured)).total_seconds() if captured else None
    report = item["report"]
    return {
        "id": profile_id,
        "profile": item["profile"],
        "contracts": item["contracts"],
        "state": item["state"],
        "expires_at": item["expires_at"],
        "config_digest": signature,
        "active_contract_ids": active,
        "captured_at": captured,
        "evidence_fresh": age is not None and 0 <= age <= maximum_evidence_age,
        "dependency_health": {
            contract_id: repository.get("continuity_health", "continuity-health:" + contract_id)
            for contract_id in item["profile"]["contract_ids"]
        },
        "rehearsal_report": {
            "eligible": report["eligible"],
            "cases": len(report["cases"]),
            "failed_cases": sum(not case["passed"] for case in report["cases"]),
            "uncovered_contract_ids": report["uncovered_contract_ids"],
        },
    }
