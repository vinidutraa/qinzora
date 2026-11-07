import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from .engine import evaluate_counts, matches, simulate
from .models import Event, Policy, now
from .store import Store


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require(value, message="Not found"):
    if value is None:
        raise HTTPException(404, message)
    return value


def rows_from_db(rows):
    return [
        {
            "event": Event.model_validate_json(r["data"]),
            "at": datetime.fromisoformat(r["received"]),
            "seq": r["seq"],
        }
        for r in rows
    ]


def policies(db, tenant):
    # Count is bounded at policy creation; never silently truncate evaluation.
    return Store.listing(db, tenant, "policy", limit=1000)


def record(db, tenant: str, event: Event, enforce: bool):
    previous = db.execute(
        "SELECT data,result FROM events WHERE tenant=? AND event_id=?", (tenant, event.event_id)
    ).fetchone()
    if previous:
        if Event.model_validate_json(previous["data"]) != event:
            raise HTTPException(409, "event_id already used with different content")
        old = json.loads(previous["result"])
        if old["mode"] != ("enforce" if enforce else "observe"):
            raise HTTPException(409, "event_id already used in another mode")
        return {**old, "duplicate": True}
    account = db.execute("SELECT event_limit FROM tenants WHERE id=?", (tenant,)).fetchone()
    count = db.execute("SELECT count(*) FROM events WHERE tenant=?", (tenant,)).fetchone()[0]
    if count >= account["event_limit"]:
        raise HTTPException(429, "Retained event capacity reached; export and prune old events")
    timestamp = now()
    counters = {}
    findings, blocks = [], []
    for item in policies(db, tenant):
        if item["state"] == "revoked":
            continue
        policy = Policy.model_validate(item["policy"])
        if not matches(policy, event):
            continue
        requests, errors = 0, 0
        if policy.kind in ("rate_limit", "error_burst"):
            if policy.window_seconds not in counters:
                counters[policy.window_seconds] = db.execute(
                    "SELECT count(*),coalesce(sum(status_code>=400),0) FROM events "
                    "WHERE tenant=? AND service=? AND route=? AND subject=? "
                    "AND received>? AND received<=?",
                    (
                        tenant,
                        event.service,
                        event.route,
                        event.subject,
                        (timestamp - timedelta(seconds=policy.window_seconds)).isoformat(),
                        timestamp.isoformat(),
                    ),
                ).fetchone()
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
    db.execute(
        "INSERT INTO events(tenant,event_id,received,service,route,subject,"
        "status_code,data,result) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            tenant,
            event.event_id,
            timestamp.isoformat(),
            event.service,
            event.route,
            event.subject,
            event.status_code,
            event.model_dump_json(),
            json.dumps(result),
        ),
    )
    if findings:
        Store.put(
            db,
            tenant,
            "incident",
            {"event_id": event.event_id, "findings": findings, "at": timestamp.isoformat()},
        )
    return result


def run_simulation(db, tenant: str, policy_id: str):
    item = require(Store.get(db, tenant, "policy", policy_id))
    policy = Policy.model_validate(item["policy"])
    count = db.execute("SELECT count(*) FROM events WHERE tenant=?", (tenant,)).fetchone()[0]
    if count > 100000:
        raise HTTPException(413, "Replay exceeds 100000 events; prune retained data first")
    rows = rows_from_db(db.execute("SELECT * FROM events WHERE tenant=? ORDER BY seq", (tenant,)))
    report = simulate(policy, rows)
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
    Store.put(db, tenant, "simulation", report, simulation_id)
    Store.audit(
        db, tenant, "simulation.created", {"simulation_id": simulation_id, "policy_id": policy_id}
    )
    return {"id": simulation_id, **report}
