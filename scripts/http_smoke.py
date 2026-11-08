"""Real loopback HTTP, temporary storage and graceful shutdown."""

import asyncio
import json
import secrets
import socket
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from qinzora.app import create_app
from qinzora.client import AsyncQinzoraClient
from qinzora.models import Event


def main():
    with tempfile.TemporaryDirectory(prefix="qinzora-http-") as directory:
        token = secrets.token_urlsafe(32)
        app = create_app(str(Path(directory) / "smoke.sqlite"), token)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    if not thread.is_alive():
                        raise RuntimeError("Server stopped before readiness")
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Readiness timeout")
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False
                ) as client:
                    assert client.get("/healthz").status_code == 200
                    assert client.get("/v1/policies").status_code == 401
                    response = client.post(
                        "/v1/admin/tenants",
                        json={"name": "HTTP smoke"},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    response.raise_for_status()
                    keys = response.json()
                    manager = {"Authorization": f"Bearer {keys['manager_key']}"}
                    collector = {"Authorization": f"Bearer {keys['collector_key']}"}
                    policy = client.post(
                        "/v1/policies",
                        headers=manager,
                        json={"name": "isolation", "service": "docs", "kind": "tenant_isolation"},
                    )
                    policy.raise_for_status()
                    pid = policy.json()["id"]
                    event = {
                        "event_id": "tcp-observe",
                        "service": "docs",
                        "route": "/docs/{id}",
                        "subject": "u",
                        "actor_tenant": "a",
                        "resource_tenant": "b",
                    }
                    observed = client.post("/v1/events", headers=collector, json=event)
                    observed.raise_for_status()
                    report = client.post(f"/v1/policies/{pid}/simulate", headers=manager)
                    report.raise_for_status()
                    activated = client.post(
                        f"/v1/policies/{pid}/activate",
                        headers=manager,
                        json={"simulation_id": report.json()["id"], "acknowledge_impact": True},
                    )
                    activated.raise_for_status()
                    blocked = client.post(
                        "/v1/decisions", headers=collector, json={**event, "event_id": "tcp-block"}
                    )
                    blocked.raise_for_status()
                    assert not blocked.json()["allowed"]

                    async def check_async_client():
                        async with AsyncQinzoraClient(
                            f"http://127.0.0.1:{port}", keys["collector_key"]
                        ) as sdk:
                            attempt = Event(**{**event, "event_id": "tcp-async"})
                            first = await sdk.decide(attempt)
                            retry = await sdk.decide(attempt)
                            assert not first["allowed"] and not retry["allowed"]
                            assert retry["duplicate"]

                    asyncio.run(check_async_client())
                    assert client.get("/openapi.json").status_code == 200
                    print(
                        json.dumps(
                            {
                                "transport": "real HTTP over loopback",
                                "passed": True,
                                "checks": [
                                    "readiness",
                                    "authentication",
                                    "provisioning",
                                    "observe",
                                    "simulate",
                                    "activate",
                                    "deny",
                                    "OpenAPI",
                                    "async_sdk_denial_and_idempotency",
                                ],
                            }
                        )
                    )
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError("Server did not stop gracefully")


if __name__ == "__main__":
    main()
