"""Two independent processes, real HTTP and graceful failure/recovery demonstration."""

import secrets
import socket
import tempfile
import time
from pathlib import Path

import httpx

from .lab import ProcessServer


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_live_demo(announce=None):
    steps = []

    def step(name, **detail):
        steps.append({"step": name, **detail})
        if announce:
            announce(name, detail)

    with tempfile.TemporaryDirectory(prefix="sentinel-integration-") as directory:
        config = {
            "db": str(Path(directory) / "demo.sqlite"),
            "admin": secrets.token_urlsafe(32),
            "port": free_port(),
        }
        guard = ProcessServer("sentinel", config)
        with guard, httpx.Client(base_url=guard.url, timeout=10, trust_env=False) as control:
            response = control.post(
                "/v1/admin/tenants",
                json={"name": "Fictional integration"},
                headers={"Authorization": f"Bearer {config['admin']}"},
            )
            response.raise_for_status()
            keys = response.json()
            manager = {"Authorization": f"Bearer {keys['manager_key']}"}

            def post(path, body=None):
                response = control.post(path, headers=manager, json=body)
                response.raise_for_status()
                return response.json()

            pid = post(
                "/v1/policies",
                {"name": "Company isolation", "service": "documents", "kind": "tenant_isolation"},
            )["id"]
            doc_config = {
                "port": free_port(),
                "sentinel_url": guard.url,
                "collector": keys["collector_key"],
                "timeout": 0.5,
            }
            with ProcessServer("documents", doc_config) as documents:
                step("independent_processes", passed=guard.process.pid != documents.process.pid)
                with httpx.Client(base_url=documents.url, timeout=5, trust_env=False) as client:
                    headers = {"Authorization": "Bearer demo-a"}
                    assert client.get("/documents/a").status_code == 401
                    assert (
                        client.get("/documents/a", headers={"Authorization": "demo-a"}).status_code
                        == 401
                    )
                    own = client.get("/documents/a", headers=headers)
                    assert own.status_code == 200
                    step("own_company_access", status=own.status_code)
                    before = client.get("/documents/b", headers=headers)
                    assert before.status_code == 403
                    assert before.json()["detail"] == "Application authorization denied access"
                    step("candidate_only_observes", application_still_enforces=True)
                    report = post(f"/v1/policies/{pid}/simulate")
                    assert report["affected_count"] == 1
                    step(
                        "historical_simulation",
                        affected=report["affected_count"],
                        matching=report["matching_events"],
                    )
                    post(
                        f"/v1/policies/{pid}/activate",
                        {"simulation_id": report["id"], "acknowledge_impact": True},
                    )
                    blocked = client.get("/documents/b", headers=headers)
                    assert blocked.status_code == 403
                    assert blocked.json()["detail"] == "Policy denied access"
                    step("activated_policy_denies", status=blocked.status_code)
                    assert client.get("/documents/a", headers=headers).status_code == 200
                    post(f"/v1/policies/{pid}/revoke")
                    revoked = client.get("/documents/b", headers=headers)
                    assert revoked.json()["detail"] == "Application authorization denied access"
                    step("revocation", application_authorization_preserved=True)
                    rate = post(
                        "/v1/policies",
                        {
                            "name": "Limit attempts",
                            "service": "documents",
                            "kind": "rate_limit",
                            "threshold": 20,
                        },
                    )["id"]
                    simulation = post(f"/v1/policies/{rate}/simulate")
                    post(
                        f"/v1/policies/{rate}/activate",
                        {"simulation_id": simulation["id"], "acknowledge_impact": True},
                    )
                    statuses = [
                        client.get("/documents/a", headers=headers).status_code for _ in range(25)
                    ]
                    assert 200 in statuses and 403 in statuses
                    step(
                        "rate_limit_on_real_application",
                        allowed=statuses.count(200),
                        denied=statuses.count(403),
                    )
                    post(f"/v1/policies/{rate}/revoke")
                    guard.close()
                    started = time.perf_counter()
                    unavailable = client.get("/documents/a", headers=headers)
                    elapsed = (time.perf_counter() - started) * 1000
                    assert unavailable.status_code == 503
                    assert "text" not in unavailable.json()
                    step(
                        "dependency_outage",
                        status=503,
                        elapsed_ms=round(elapsed, 2),
                        data_disclosed=False,
                    )
                    with ProcessServer("sentinel", config):
                        recovered = client.get("/documents/a", headers=headers)
                        assert recovered.status_code == 200
                        step("restart_and_recovery", status=200, database_preserved=True)
            return {
                "passed": True,
                "transport": "two processes over real loopback HTTP",
                "steps": steps,
                "data": "synthetic only",
            }
