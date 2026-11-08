import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

from .engine import evaluate_counts, matches, simulate
from .errors import ApplicationError, require
from .models import Activation, Event, Policy, now
from .ports import Repository


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_policy(repository: Repository, policy: Policy) -> dict:
    if len(repository.policies()) >= 100:
        raise ApplicationError("conflict", "Maximum of 100 policies per account")
    item = {"policy": policy.model_dump(), "state": "candidate", "expires_at": None}
    policy_id = repository.put("policy", item)
    repository.audit("policy.created", {"policy_id": policy_id})
    return {"id": policy_id, **item}


def activate_policy(repository: Repository, policy_id: str, activation: Activation) -> dict:
    item = require(repository.get("policy", policy_id))
    report = require(repository.get("simulation", activation.simulation_id))
    policy = Policy.model_validate(item["policy"])
    if item["state"] != "candidate":
        raise ApplicationError("conflict", "Only candidate policies can be activated")
    if report["policy_id"] != policy_id or report["policy_digest"] != digest(
        policy.model_dump_json()
    ):
        raise ApplicationError("conflict", "Simulation does not match policy")
    timestamp = now()
    age = timestamp - datetime.fromisoformat(report["created_at"])
    if age < timedelta(0) or age > timedelta(minutes=15):
        raise ApplicationError("conflict", "Simulation expired or clock changed; run again")
    if not report["activation_eligible"]:
        raise ApplicationError("conflict", "No matching evidence or observation-only policy")
    if not activation.acknowledge_impact:
        raise ApplicationError("conflict", "Review simulation and acknowledge its impact")
    item.update(
        state="active",
        expires_at=(timestamp + timedelta(seconds=policy.ttl_seconds)).isoformat(),
        simulation_id=activation.simulation_id,
    )
    repository.put("policy", item, policy_id)
    repository.audit(
        "policy.activated", {"policy_id": policy_id, "simulation_id": activation.simulation_id}
    )
    return {"id": policy_id, **item}


def revoke_policy(repository: Repository, policy_id: str) -> dict:
    item = require(repository.get("policy", policy_id))
    item["state"] = "revoked"
    repository.put("policy", item, policy_id)
    repository.audit("policy.revoked", {"policy_id": policy_id})
    return {"id": policy_id, **item}


def record(repository: Repository, event: Event, enforce: bool):
    previous = repository.previous_event(event.event_id)
    if previous:
        if previous[0] != event:
            raise ApplicationError("conflict", "event_id already used with different content")
        old = previous[1]
        if old["mode"] != ("enforce" if enforce else "observe"):
            raise ApplicationError("conflict", "event_id already used in another mode")
        return {**old, "duplicate": True}
    if repository.event_count() >= repository.event_limit():
        raise ApplicationError(
            "capacity_exceeded", "Retained event capacity reached; export and prune old events"
        )
    timestamp = now()
    latest = repository.latest_timestamp()
    if latest is not None and timestamp < latest:
        raise ApplicationError("conflict", "Event clock moved backwards; decision refused")
    counters = {}
    findings, blocks = [], []
    for item in repository.policies():
        if item["state"] == "revoked":
            continue
        policy = Policy.model_validate(item["policy"])
        if not matches(policy, event):
            continue
        requests, errors = 0, 0
        if policy.kind in ("rate_limit", "error_burst"):
            if policy.window_seconds not in counters:
                counters[policy.window_seconds] = repository.counts(
                    event, timestamp - timedelta(seconds=policy.window_seconds), timestamp
                )
            requests, errors = counters[policy.window_seconds]
        reason = evaluate_counts(policy, event, requests, errors)
        if not reason:
            continue
        active = (
            item["state"] == "active" and datetime.fromisoformat(item["expires_at"]) > timestamp
        )
        evidence = {
            "policy_id": item["id"],
            "reason": reason,
            "event_id": event.event_id,
            "service": event.service,
            "route": event.route,
            "subject": event.subject,
            "active": active,
        }
        findings.append(evidence)
        # Latency and error signals describe completed responses. Never block on them.
        if enforce and active and policy.kind in ("rate_limit", "tenant_isolation"):
            blocks.append(evidence)
    result = {
        "event_id": event.event_id,
        "mode": "enforce" if enforce else "observe",
        "allowed": not blocks,
        "findings": findings,
        "blocks": blocks,
        "received_at": timestamp.isoformat(),
        "duplicate": False,
    }
    repository.append_event(event, timestamp, result)
    if findings:
        repository.put(
            "incident",
            {"event_id": event.event_id, "findings": findings, "at": timestamp.isoformat()},
        )
    return result


def run_simulation(repository: Repository, policy_id: str):
    item = require(repository.get("policy", policy_id))
    policy = Policy.model_validate(item["policy"])
    count = repository.event_count()
    if count > 100000:
        raise ApplicationError(
            "replay_too_large", "Replay exceeds 100000 events; prune retained data first"
        )
    rows = repository.snapshot()
    try:
        report = simulate(policy, rows)
    except ValueError as exc:
        raise ApplicationError("conflict", "Event clock is inconsistent; replay refused") from exc
    simulation_id = str(uuid4())
    report.update(
        {
            "policy_id": policy_id,
            "policy_digest": digest(policy.model_dump_json()),
            "watermark": rows[-1]["seq"] if rows else 0,
            "created_at": now().isoformat(),
            "activation_eligible": bool(report["matching_events"])
            and policy.kind in ("rate_limit", "tenant_isolation"),
        }
    )
    repository.put("simulation", report, simulation_id)
    repository.audit("simulation.created", {"simulation_id": simulation_id, "policy_id": policy_id})
    return {"id": simulation_id, **report}
