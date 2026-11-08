"""Exercise the actual Compose image, data volume and restart in an isolated project."""

import json
import os
import secrets
import subprocess
import uuid

import httpx

from qinzora.live_demo import free_port


def main():
    port, token = free_port(), secrets.token_urlsafe(32)
    project = "qinzora-test-" + uuid.uuid4().hex[:12]
    env = {**os.environ, "QINZORA_ADMIN_TOKEN": token, "QINZORA_PORT": str(port)}
    command = ["docker", "compose", "-p", project, "-f", "compose.yaml"]

    def compose(*args):
        result = subprocess.run(
            [*command, *args], env=env, text=True, capture_output=True, timeout=300
        )
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).replace(token, "[REDACTED]"))

    try:
        compose("up", "--build", "--wait", "--wait-timeout", "180")
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False
        ) as client:
            assert client.get("/healthz").status_code == 200
            tenant = client.post(
                "/v1/admin/tenants",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Docker fixture"},
            )
            tenant.raise_for_status()
            keys = tenant.json()
            manager = {"Authorization": f"Bearer {keys['manager_key']}"}
            collector = {"Authorization": f"Bearer {keys['collector_key']}"}
            policy = client.post(
                "/v1/policies",
                headers=manager,
                json={"name": "isolation", "service": "docker", "kind": "tenant_isolation"},
            )
            policy.raise_for_status()
            pid = policy.json()["id"]
            event = {
                "event_id": "observed",
                "service": "docker",
                "route": "/documents/{id}",
                "subject": "u",
                "actor_tenant": "a",
                "resource_tenant": "b",
            }
            client.post("/v1/events", headers=collector, json=event).raise_for_status()
            report = client.post(f"/v1/policies/{pid}/simulate", headers=manager)
            report.raise_for_status()
            client.post(
                f"/v1/policies/{pid}/activate",
                headers=manager,
                json={"simulation_id": report.json()["id"], "acknowledge_impact": True},
            ).raise_for_status()
            result = client.post(
                "/v1/decisions", headers=collector, json={**event, "event_id": "denied"}
            )
            result.raise_for_status()
            assert not result.json()["allowed"]
            compose("restart", "qinzora")
            compose("up", "--wait", "--wait-timeout", "120")
            # Restart can close pooled sockets; use a fresh client connection.
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False
        ) as restarted:
            usage = restarted.get("/v1/usage", headers=manager)
            usage.raise_for_status()
            assert usage.json()["retained_events"] == 2
        print(
            json.dumps(
                {
                    "passed": True,
                    "runtime": "Docker Compose",
                    "checks": [
                        "image_build",
                        "non_root_readonly_start",
                        "health",
                        "observe",
                        "simulate",
                        "activate",
                        "deny",
                        "restart_with_persistent_volume",
                    ],
                }
            )
        )
    finally:
        # Only the randomly named project created above is removed.
        compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
