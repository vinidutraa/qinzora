"""Bounded operational summaries; no request bodies, identities or model tools."""

import json
from collections import Counter

from ..errors import ApplicationError
from ..models import Policy, now
from ..ports import Repository
from ..service import digest
from .contracts import Authority


def fingerprint(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def policy_inventory(repository: Repository, authority: Authority) -> list[dict]:
    return sorted(
        (
            item
            for item in repository.policies()
            if authority.permits(Policy.model_validate(item["policy"]))
        ),
        key=lambda item: item["id"],
    )


def capture_context(repository: Repository, authority: Authority) -> dict:
    if repository.event_count() > 100000:
        raise ApplicationError("replay_too_large", "Administration snapshot exceeds 100000 events")
    inventory = policy_inventory(repository, authority)
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
        "summaries": summaries,
        "authority": authority.model_dump(),
        "limitations": "Aggregates describe retained attempts, not causal proof. Labels are "
        "supplied by the application. Execution replays current evidence before enforcement.",
    }
