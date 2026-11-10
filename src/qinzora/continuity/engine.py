"""Pure checks shared by rehearsal and request-time fallback validation."""

from .contracts import OperationContract, Rehearsal, SnapshotEvidence


def evaluate_rules(contract: OperationContract, data: dict) -> dict[str, bool]:
    """Compare declared scalar values without eval, scripts or model-generated predicates."""
    results = {}
    for rule in contract.value_rules:
        actual = data.get(rule.field)
        if type(rule.expected) is int:
            compatible = type(actual) in (int, float)
        else:
            compatible = type(actual) is type(rule.expected)
        results[rule.name] = compatible and actual == rule.expected
    return results


def violations(contract: OperationContract, observed: SnapshotEvidence) -> list[str]:
    reasons = []
    if not observed.authorized:
        reasons.append("authorization_required")
    if not observed.same_tenant:
        reasons.append("tenant_scope_mismatch")
    if not observed.consumer_matches:
        reasons.append("consumer_mismatch")
    if contract.effect != "read" or not contract.allow_cached:
        reasons.append("cached_response_not_permitted")
    if not observed.available:
        reasons.append("snapshot_missing")
    if observed.age_seconds > contract.maximum_age_seconds:
        reasons.append("snapshot_too_old")
    if set(contract.required_fields) - set(observed.fields):
        reasons.append("required_fields_missing")
    reasons.extend(
        "value_rule_failed:" + rule.name
        for rule in contract.value_rules
        if observed.rule_results.get(rule.name) is not True
    )
    return reasons


def simulate(contracts: dict[str, OperationContract], rehearsal: Rehearsal) -> dict:
    cases, covered = [], set()
    for scenario in rehearsal.scenarios:
        if scenario.contract_id not in contracts:
            raise ValueError("Scenario references a contract outside the profile")
        covered.add(scenario.contract_id)
        reasons = violations(contracts[scenario.contract_id], scenario.observed)
        decision = "deny" if reasons else "permit"
        cases.append(
            {
                "name": scenario.name,
                "contract_id": scenario.contract_id,
                "decision": decision,
                "expected": scenario.expected,
                "passed": decision == scenario.expected,
                "reasons": reasons,
            }
        )
    missing = sorted(set(contracts) - covered)
    return {
        "eligible": not missing
        and all(case["passed"] for case in cases)
        and any(case["decision"] == "permit" for case in cases),
        "cases": cases,
        "uncovered_contract_ids": missing,
        "limitation": "Metadata rehearsal, not execution of business operations or proof "
        "of future availability. The application supplies scenarios and expectations; "
        "live snapshots must pass the same checks again.",
    }
