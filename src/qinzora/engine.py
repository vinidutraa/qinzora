"""Pure policy engine shared by replay and live decisions. No LLM in authorization."""

from collections import defaultdict, deque
from datetime import datetime, timedelta

from .models import Event, Policy, RouteContract


def matches(policy: Policy, event: Event) -> bool:
    return policy.service == event.service and policy.route in ("*", event.route)


def evaluate(policy: Policy, event: Event, timestamp: datetime, history: list[dict]) -> str | None:
    cutoff = timestamp - timedelta(seconds=policy.window_seconds)
    relevant = [
        row
        for row in history
        if cutoff < row["at"] <= timestamp
        and row["event"].service == event.service
        and row["event"].route == event.route
        and row["event"].subject == event.subject
    ]
    failures = sum(row["event"].status_code >= 400 for row in relevant)
    return evaluate_counts(policy, event, len(relevant), failures)


def evaluate_counts(policy: Policy, event: Event, requests: int = 0, errors: int = 0):
    """Same decision function for SQL counters, reference evaluation and replay."""
    if not matches(policy, event):
        return None
    if policy.kind == "tenant_isolation":
        if event.actor_tenant is None or event.resource_tenant is None:
            return "missing_tenant_context"
        return "cross_tenant_access" if event.actor_tenant != event.resource_tenant else None
    if policy.kind == "latency":
        return "high_latency" if event.latency_ms > policy.threshold else None
    if policy.kind == "rate_limit":
        return "request_rate_exceeded" if requests + 1 > policy.threshold else None
    return "error_burst" if event.status_code >= 400 and errors + 1 >= policy.threshold else None


def simulate(policy: Policy, rows: list[dict]) -> dict:
    windows = defaultdict(deque)
    error_counts = defaultdict(int)
    reasons = defaultdict(int)
    affected_ids = []
    labels = {"legitimate": 0, "abusive": 0, "unknown": 0}
    totals = dict(labels)
    previous_timestamp = None
    for row in rows:
        event, timestamp = row["event"], row["at"]
        if timestamp.utcoffset() is None:
            raise ValueError("Replay requires timezone-aware timestamps")
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValueError("Replay timestamps must follow ingestion order")
        previous_timestamp = timestamp
        if not matches(policy, event):
            continue
        totals[event.expected] += 1
        key = (event.service, event.route, event.subject)
        history = windows[key]
        cutoff = timestamp - timedelta(seconds=policy.window_seconds)
        while history and history[0]["at"] <= cutoff:
            removed = history.popleft()
            error_counts[key] -= int(removed["event"].status_code >= 400)
        # Linear-time replay even when many requests share the same time window.
        reason = evaluate_counts(policy, event, len(history), error_counts[key])
        if reason:
            reasons[reason] += 1
            affected_ids.append(event.event_id)
            labels[event.expected] += 1
        history.append(row)
        error_counts[key] += int(event.status_code >= 400)
    return {
        "events_in_snapshot": len(rows),
        "matching_events": sum(totals.values()),
        "affected_count": len(affected_ids),
        "affected_event_ids": affected_ids[:100],
        "affected_ids_truncated": len(affected_ids) > 100,
        "reasons": dict(reasons),
        "affected_labels": labels,
        "total_labels": totals,
        "false_positive_rate": labels["legitimate"] / totals["legitimate"]
        if totals["legitimate"]
        else None,
        "limitation": "Historical impact estimate, not proof of future safety. Labels are supplied "
        "by the integrator. Replay counts observed attempts, including denied attempts.",
    }


def regressions(baseline: list[RouteContract], current: list[RouteContract]) -> list[dict]:
    def index(routes):
        result = {(r.method, r.path): r for r in routes}
        if len(result) != len(routes):
            raise ValueError("Duplicate method/path in route manifest")
        return result

    before, after = index(baseline), index(current)
    findings = []
    for key, route in after.items():
        old = before.get(key)
        for field in ("authenticated", "tenant_isolation"):
            if (old and getattr(old, field) and not getattr(route, field)) or (
                old is None and not getattr(route, field)
            ):
                findings.append(
                    {
                        "method": key[0],
                        "path": key[1],
                        "control": field,
                        "reason": "weakened" if old else "new_unprotected_route",
                    }
                )
    return findings
