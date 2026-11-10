"""Bounded operational summaries; no request bodies, identities or model tools."""

from collections import Counter

from ..continuity.service import profile_summary
from ..errors import ApplicationError
from ..models import Policy, now
from ..ports import Repository
from ..serialization import fingerprint
from .contracts import Authority


def policy_inventory(repository: Repository, authority: Authority) -> list[dict]:
    return sorted(
        (
            item
            for item in repository.policies()
            if authority.permits(Policy.model_validate(item["policy"]))
        ),
        key=lambda item: item["id"],
    )


def continuity_inventory(repository: Repository, authority: Authority) -> list[dict]:
    profiles = []
    for profile_id in sorted(set(authority.continuity_profile_ids)):
        item = profile_summary(
            repository, profile_id, authority.maximum_continuity_evidence_age_seconds
        )
        profile = item["profile"]
        if not authority.permits_scope(profile["service"], profile["route"]):
            raise ApplicationError("conflict", "Continuity profile is outside managed scope")
        profiles.append(item)
    return profiles


def continuity_revision(profiles: list[dict]) -> str:
    # Live dependency signals may change during inference. Configuration and rehearsals may not.
    return fingerprint(
        [
            {key: value for key, value in item.items() if key != "dependency_health"}
            for item in profiles
        ]
    )


def capture_context(repository: Repository, authority: Authority) -> dict:
    if repository.event_count() > 100000:
        raise ApplicationError("replay_too_large", "Administration snapshot exceeds 100000 events")
    inventory = policy_inventory(repository, authority)
    continuity = continuity_inventory(repository, authority)
    rows = repository.snapshot()
    # One summary per granted scope bounds output independently of observed routes/identities.
    summaries = []
    for scope in authority.routes:
        counts = Counter()
        for row in rows:
            event = row["event"]
            if event.service != scope.service or scope.route not in ("*", event.route):
                continue
            counts["attempts"] += 1
            counts["http_errors"] += event.status_code >= 400
            counts["missing_tenant_context"] += (
                event.actor_tenant is None or event.resource_tenant is None
            )
            counts["cross_tenant_attempts"] += (
                event.actor_tenant is not None
                and event.resource_tenant is not None
                and event.actor_tenant != event.resource_tenant
            )
            counts[event.expected] += 1
        summaries.append({**scope.model_dump(), "counts": dict(counts)})
    return {
        "created_at": now().isoformat(),
        "policy_revision": fingerprint(inventory),
        "watermark": rows[-1]["seq"] if rows else 0,
        "retained_events": len(rows),
        "policies": inventory,
        "continuity_profiles": continuity,
        "continuity_revision": continuity_revision(continuity),
        "summaries": summaries,
        "authority": authority.model_dump(),
        "limitations": "Aggregates describe retained attempts, not causal proof. Labels are "
        "supplied by the application. Execution replays current evidence before enforcement.",
    }
