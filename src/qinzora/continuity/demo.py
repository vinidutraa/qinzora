"""Synthetic shipping scenario with real HTTP management and registered adapters."""

from contextlib import AsyncExitStack
from datetime import timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx

from ..administration.contracts import Authority
from ..administration.controller import Administrator
from ..lab import ProcessServer
from ..live_demo import free_port
from ..models import now
from ..providers import HTTPStructuredModel
from ..repository import account_transaction
from ..store import Store
from .runtime import (
    CachedResponse,
    ContinuityRuntime,
    ContinuityUnavailable,
    DependencyUnavailable,
    VerifiedCall,
)


class DemonstrationPlanner:
    """Scripted selection for a reproducible demo; never presented as model inference."""

    async def generate(self, system, context, result_type):
        candidates = [
            item
            for item in context["continuity_profiles"]
            if item["rehearsal_report"]["eligible"] and item["evidence_fresh"]
        ]
        return result_type.model_validate(
            {
                "rationale": "Scripted demonstration: select the passing rehearsal.",
                "operations": [{"action": "activate_continuity", "profile_id": candidates[0]["id"]}]
                if candidates
                else [],
            }
        )


async def run_continuity_demo(
    model: str | None = None, base_url: str = "http://127.0.0.1:11434"
) -> dict:
    import secrets

    with TemporaryDirectory(prefix="qinzora-continuity-") as directory:
        database = str(Path(directory) / "qinzora.sqlite")
        token = secrets.token_urlsafe(48)
        with ProcessServer(
            "qinzora", {"db": database, "admin": token, "port": free_port()}
        ) as server:
            with httpx.Client(base_url=server.url, trust_env=False, timeout=5) as client:
                response = client.post(
                    "/v1/admin/tenants",
                    headers={"Authorization": "Bearer " + token},
                    json={"name": "Synthetic shipping service"},
                )
                response.raise_for_status()
                account = response.json()
                client.headers["Authorization"] = "Bearer " + account["manager_key"]

                def post(path: str, body: dict[str, Any]):
                    response = client.post(path, json=body)
                    response.raise_for_status()
                    return response.json()

                common = {
                    "service": "shipping",
                    "route": "/shipping",
                    "required_fields": ["amount", "currency"],
                    "value_rules": [{"name": "currency", "field": "currency", "expected": "BRL"}],
                }
                read = post(
                    "/v1/continuity/contracts",
                    {
                        **common,
                        "consumer": "storefront",
                        "effect": "read",
                        "allow_cached": True,
                        "maximum_age_seconds": 900,
                    },
                )["id"]
                write = post(
                    "/v1/continuity/contracts",
                    {**common, "consumer": "checkout", "effect": "write"},
                )["id"]
                observed = {
                    "available": True,
                    "age_seconds": 120,
                    "fields": ["amount", "currency"],
                    "authorized": True,
                    "same_tenant": True,
                    "consumer_matches": True,
                    "rule_results": {"currency": True},
                }
                cases = [
                    {
                        "name": "estimate",
                        "contract_id": read,
                        "observed": observed,
                        "expected": "permit",
                    },
                    {
                        "name": "expired",
                        "contract_id": read,
                        "observed": {**observed, "age_seconds": 901},
                        "expected": "deny",
                    },
                    {
                        "name": "checkout",
                        "contract_id": write,
                        "observed": observed,
                        "expected": "deny",
                    },
                    {
                        "name": "wrong currency",
                        "contract_id": read,
                        "observed": {**observed, "rule_results": {"currency": False}},
                        "expected": "deny",
                    },
                ]
                profiles, reports = [], []
                for stale in (False, True):
                    profile = post(
                        "/v1/continuity/profiles",
                        {
                            "name": "stale backup" if stale else "local estimates",
                            "service": "shipping",
                            "route": "/shipping",
                            "source": "stale_backup" if stale else "local_estimates",
                            "contract_ids": [read, write],
                            "ttl_seconds": 120,
                        },
                    )["id"]
                    samples = [dict(case) for case in cases]
                    if stale:
                        samples[0] = {**samples[0], "observed": {**observed, "age_seconds": 3600}}
                    response = client.put(
                        f"/v1/continuity/profiles/{profile}/rehearsal",
                        json={"captured_at": now().isoformat(), "scenarios": samples},
                    )
                    response.raise_for_status()
                    reports.append(post(f"/v1/continuity/profiles/{profile}/simulate", {}))
                    profiles.append(profile)
            repository = partial(account_transaction, Store(database), account["id"])

            async def offline():
                raise DependencyUnavailable("synthetic shipping provider outage")

            call = VerifiedCall("storefront", "demo-company", "demo-company", True)
            # Observe the actual adapter failure before asking for a response plan.
            try:
                await ContinuityRuntime(repository, {}).run(read, call, offline)
            except ContinuityUnavailable:
                pass
            authority = Authority(
                routes=[{"service": "shipping", "route": "/shipping"}],
                allow_stage=False,
                allow_enforce=False,
                continuity_profile_ids=profiles,
                objective="Maintain shipping estimates during outages. Activate only the fresh, "
                "passing continuity profile; never allow cached checkout writes or wrong currency.",
            )
            async with AsyncExitStack() as stack:
                planner = (
                    await stack.enter_async_context(HTTPStructuredModel("ollama", base_url, model))
                    if model
                    else DemonstrationPlanner()
                )
                administrator = Administrator(repository, planner, authority)
                plan = await administrator.propose()
                execution = administrator.execute(plan["id"])
            selected = [
                {"action": result["action"], "profile_id": result.get("profile_id")}
                for result in execution["results"]
            ]
            if not any(
                result["action"] == "activate_continuity" and result["profile_id"] == profiles[0]
                for result in selected
            ):
                return {
                    "passed": False,
                    "inference": "real Ollama" if model else "scripted",
                    "model": model,
                    "actions": selected,
                    "rationale": plan["proposal"]["rationale"],
                    "reason": (
                        "The planner did not activate the passing profile; "
                        "no scripted fallback used"
                    ),
                }
            age, currency, loads = 120, "BRL", 0

            async def healthy():
                return {"amount": 14, "currency": "BRL"}

            async def cached(contract_id, call):
                nonlocal loads
                loads += 1
                return CachedResponse(
                    {"amount": 12, "currency": currency},
                    now() - timedelta(seconds=age),
                    "storefront",
                    "demo-company",
                )

            runtime = ContinuityRuntime(repository, {"local_estimates": cached})
            steps = [
                {
                    "step": "compare_rehearsals",
                    "passed": reports[0]["eligible"] and not reports[1]["eligible"],
                },
                {"step": "activate_registered_profile", "passed": execution["state"] == "executed"},
            ]

            async def denied(contract_id, context, reason):
                try:
                    await runtime.run(contract_id, context, offline)
                except ContinuityUnavailable as exc:
                    return reason in exc.reasons
                return False

            result = await runtime.run(read, call, offline)
            steps.append(
                {
                    "step": "read_fallback",
                    "passed": result.source == "cache" and result.data["amount"] == 12,
                }
            )
            before = loads
            denied_write = await denied(
                write,
                VerifiedCall("checkout", "demo-company", "demo-company", True),
                "cached_response_not_permitted",
            )
            steps.append(
                {"step": "checkout_no_cached_write", "passed": denied_write and loads == before}
            )
            age = 901
            steps.append(
                {
                    "step": "reject_expired_live_snapshot",
                    "passed": await denied(read, call, "snapshot_too_old"),
                }
            )
            age, currency = 120, "USD"
            steps.append(
                {
                    "step": "reject_wrong_currency",
                    "passed": await denied(read, call, "value_rule_failed:currency"),
                }
            )
            currency = "BRL"
            restored = await runtime.run(read, call, healthy)
            steps.append(
                {
                    "step": "primary_recovery",
                    "passed": restored.source == "primary" and restored.data["amount"] == 14,
                }
            )
            return {
                "passed": all(step["passed"] for step in steps),
                "steps": steps,
                "inference": "real Ollama" if model else "scripted planner; no model inference",
                "model": model,
                "transport": "real loopback HTTP management; synthetic primary/cache adapters",
                "limitation": "Synthetic example; no guarantee of model accuracy or resilience.",
            }
