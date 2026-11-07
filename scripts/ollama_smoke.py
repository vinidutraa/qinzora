"""Real model call through the authenticated incident endpoint; no mock responses."""

import argparse
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from api_sentinel.app import create_app


def run_smoke(url, model):
    previous = {
        name: os.environ.get(name) for name in ("SENTINEL_OLLAMA_URL", "SENTINEL_OLLAMA_MODEL")
    }
    try:
        os.environ.update(SENTINEL_OLLAMA_URL=url, SENTINEL_OLLAMA_MODEL=model)
        with tempfile.TemporaryDirectory(prefix="sentinel-model-") as directory:
            token = secrets.token_urlsafe(32)
            with TestClient(create_app(str(Path(directory) / "model.sqlite"), token)) as client:
                tenant = client.post(
                    "/v1/admin/tenants",
                    json={"name": "Synthetic AI check"},
                    headers={"Authorization": f"Bearer {token}"},
                ).json()
                manager = {"Authorization": f"Bearer {tenant['manager_key']}"}
                collector = {"Authorization": f"Bearer {tenant['collector_key']}"}
                client.post(
                    "/v1/policies",
                    headers=manager,
                    json={"name": "Isolation", "service": "docs", "kind": "tenant_isolation"},
                ).raise_for_status()
                client.post(
                    "/v1/events",
                    headers=collector,
                    json={
                        "service": "docs",
                        "route": "/docs/{id}",
                        "subject": "opaque-demo-user",
                        "actor_tenant": "a",
                        "resource_tenant": "b",
                    },
                ).raise_for_status()
                incidents = client.get("/v1/incidents", headers=manager).json()
                start = time.perf_counter()
                response = client.post(
                    f"/v1/incidents/{incidents[0]['id']}/explain", headers=manager
                )
                response.raise_for_status()
                result = response.json()
                if result["source"] != "ollama" or result["model_error"] is not None:
                    raise RuntimeError(
                        "Real model did not answer; deterministic fallback is not a pass"
                    )
                return {
                    "passed": True,
                    "model": model,
                    "elapsed_seconds": round(time.perf_counter() - start, 3),
                    **result,
                    "scope": "Real inference; advisory output, not an accuracy benchmark",
                }
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_smoke(args.url, args.model)
    content = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
