"""Reproducible isolated demo using the actual API and ephemeral database."""

import secrets
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from .app import create_app


def run_demo():
    with tempfile.TemporaryDirectory(prefix="qinzora-demo-") as directory:
        admin = secrets.token_urlsafe(32)
        app = create_app(str(Path(directory) / "demo.sqlite"), admin)
        with TestClient(app) as client:

            def post(path, body, key):
                response = client.post(path, json=body, headers={"Authorization": f"Bearer {key}"})
                response.raise_for_status()
                return response.json()

            tenant = post("/v1/admin/tenants", {"name": "Fictional SaaS"}, admin)
            manager, collector = tenant["manager_key"], tenant["collector_key"]
            isolation = post(
                "/v1/policies",
                {
                    "name": "Documents belong to the same company",
                    "service": "documents",
                    "kind": "tenant_isolation",
                },
                manager,
            )
            rate = post(
                "/v1/policies",
                {
                    "name": "Limit document enumeration",
                    "service": "documents",
                    "kind": "rate_limit",
                    "threshold": 3,
                },
                manager,
            )
            for index in range(8):
                event = {
                    "event_id": f"fixture-{index}",
                    "service": "documents",
                    "route": "/documents/{id}",
                    "subject": "opaque-demo-user",
                    "actor_tenant": "company-a",
                    "resource_tenant": "company-a" if index < 3 else "company-b",
                    "expected": "legitimate" if index < 3 else "abusive",
                }
                post("/v1/events", event, collector)
            reports = [
                post(f"/v1/policies/{p['id']}/simulate", {}, manager) for p in (isolation, rate)
            ]
            post(
                f"/v1/policies/{isolation['id']}/activate",
                {"simulation_id": reports[0]["id"], "acknowledge_impact": True},
                manager,
            )
            event = {
                "service": "documents",
                "route": "/documents/{id}",
                "subject": "another-demo-user",
                "actor_tenant": "company-a",
                "resource_tenant": "company-a",
            }
            allowed = post("/v1/decisions", {**event, "event_id": "allowed"}, collector)
            denied = post(
                "/v1/decisions",
                {**event, "event_id": "denied", "resource_tenant": "company-b"},
                collector,
            )
            regression = post(
                "/v1/regressions/check",
                {
                    "baseline": [
                        {
                            "method": "GET",
                            "path": "/documents/{id}",
                            "authenticated": True,
                            "tenant_isolation": True,
                        }
                    ],
                    "current": [
                        {
                            "method": "GET",
                            "path": "/documents/{id}",
                            "authenticated": True,
                            "tenant_isolation": False,
                        }
                    ],
                },
                manager,
            )
            post(f"/v1/policies/{isolation['id']}/revoke", {}, manager)
            revoked = post(
                "/v1/decisions",
                {**event, "event_id": "after-revoke", "resource_tenant": "company-b"},
                collector,
            )
            assert allowed["allowed"] and not denied["allowed"]
            assert revoked["allowed"] and not regression["passed"]
            assert all(r["affected_count"] == 5 for r in reports)
            assert all(r["false_positive_rate"] == 0 for r in reports)
            return {
                "fixture": "8 synthetic events: 3 labeled legitimate, 5 labeled abusive",
                "simulations": reports,
                "same_company_allowed": allowed["allowed"],
                "cross_company_denied": not denied["allowed"],
                "regression": regression,
                "revocation_restored_access": revoked["allowed"],
                "note": "Synthetic demonstration, not a production efficacy benchmark. "
                "After revocation the application must still enforce its own authorization.",
            }
