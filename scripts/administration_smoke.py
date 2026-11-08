"""Real model + isolated Qinzora HTTP service. No simulated inference fallback."""

import argparse
import asyncio
import json
import secrets
import tempfile
from pathlib import Path

import httpx

from qinzora.administration.config import ManagementConfig, run_cycle, watch_service
from qinzora.errors import ApplicationError
from qinzora.lab import ProcessServer
from qinzora.live_demo import free_port
from qinzora.providers import ModelUnavailable
from qinzora.repository import account_transaction
from qinzora.store import Store


def run(
    model: str, base_url: str, provider: str, api_key_env: str | None, watch: bool = False
) -> dict:
    with tempfile.TemporaryDirectory(prefix="qinzora-administration-") as directory:
        database = str(Path(directory) / "qinzora.sqlite")
        token = secrets.token_urlsafe(48)
        with ProcessServer(
            "qinzora", {"db": database, "admin": token, "port": free_port()}
        ) as server:
            with httpx.Client(base_url=server.url, trust_env=False, timeout=5) as client:
                response = client.post(
                    "/v1/admin/tenants",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": "Synthetic administration test"},
                )
                response.raise_for_status()
                account = response.json()
                client.headers["Authorization"] = "Bearer " + account["collector_key"]
                for index in range(6):
                    event = {
                        "event_id": f"sample-{index}",
                        "service": "documents",
                        "route": "/documents/{id}",
                        "subject": "synthetic-user",
                        "actor_tenant": "a",
                        "resource_tenant": "a" if index < 2 else "b",
                        "expected": "legitimate" if index < 2 else "abusive",
                    }
                    client.post("/v1/events", json=event).raise_for_status()
                config = ManagementConfig(
                    database=database,
                    account_id=account["id"],
                    provider=provider,
                    base_url=base_url,
                    model=model,
                    api_key_env=api_key_env,
                    authority={
                        "routes": [{"service": "documents", "route": "/documents/{id}"}],
                        "allow_stage": False,
                        "allow_enforce": True,
                        "objective": "Prevent the observed cross-tenant attempts on documents. "
                        "Use a tenant_isolation policy if no such policy already exists. "
                        "Legitimate and abusive labels in this synthetic scenario are verified.",
                        "maximum_ttl_seconds": 60,
                    },
                )
                if watch:

                    async def monitor_once():
                        stop, results = asyncio.Event(), []

                        def receive(result):
                            results.append(result)
                            stop.set()

                        await watch_service(config, stop, execute=True, on_result=receive)
                        return results[0]

                    cycle = asyncio.run(monitor_once())
                    if cycle["status"] != "executed":
                        raise ApplicationError("conflict", "Monitor did not execute the test plan")
                    with account_transaction(Store(database), account["id"]) as repository:
                        plan = repository.get("administration_plan", cycle["plan_id"])
                else:
                    plan = asyncio.run(run_cycle(config, execute=True))
                response = client.post("/v1/decisions", json={**event, "event_id": "after-agent"})
                response.raise_for_status()
                decision = response.json()
                result = {
                    "passed": plan["state"] == "executed" and not decision["allowed"],
                    "model": model,
                    "provider": provider,
                    "mode": "watch" if watch else "single_cycle",
                    "transport": "real model HTTP and Qinzora HTTP",
                    "actions": [r["action"] for r in plan["results"]],
                    "rationale": plan["proposal"]["rationale"],
                    "allowed_after_execution": decision["allowed"],
                    "limitations": "Synthetic scenario; not evidence of general model accuracy.",
                }
                print(json.dumps(result, ensure_ascii=False))
                return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--provider", choices=["ollama", "chat_completions"], default="ollama")
    parser.add_argument("--api-key-env")
    parser.add_argument(
        "--watch", action="store_true", help="Exercise one continuous-monitor cycle"
    )
    args = parser.parse_args()
    try:
        result = run(args.model, args.base_url, args.provider, args.api_key_env, args.watch)
    except (ApplicationError, ModelUnavailable) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        raise SystemExit(1) from None
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
