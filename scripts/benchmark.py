"""Bounded, local synthetic workload; never target a third-party API."""

import argparse
import json
import platform
import secrets
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from qinzora.engine import simulate
from qinzora.lab import ProcessServer
from qinzora.live_demo import free_port
from qinzora.models import Event, Policy, now


def run_benchmark(requests=400, concurrency=8):
    if not 1 <= requests <= 450 or not 1 <= concurrency <= 16:
        raise ValueError("Use 1–450 requests and 1–16 workers; API limit stays enabled")
    with tempfile.TemporaryDirectory(prefix="qinzora-load-") as directory:
        config = {
            "db": str(Path(directory) / "load.sqlite"),
            "admin": secrets.token_urlsafe(32),
            "port": free_port(),
        }
        with (
            ProcessServer("qinzora", config) as server,
            httpx.Client(
                base_url=server.url,
                timeout=20,
                trust_env=False,
            ) as client,
        ):
            tenant = client.post(
                "/v1/admin/tenants",
                headers={"Authorization": f"Bearer {config['admin']}"},
                json={"name": "Synthetic load"},
            )
            tenant.raise_for_status()
            keys = tenant.json()
            manager = {"Authorization": f"Bearer {keys['manager_key']}"}
            collector = {"Authorization": f"Bearer {keys['collector_key']}"}
            policy = client.post(
                "/v1/policies",
                headers=manager,
                json={
                    "name": "Hot identity",
                    "service": "load",
                    "kind": "rate_limit",
                    "threshold": 100000,
                },
            )
            policy.raise_for_status()
            event = {"service": "load", "route": "/items/{id}", "subject": "hot-user"}
            for i in range(10):
                client.post(
                    "/v1/decisions", headers=collector, json={**event, "event_id": f"warm-{i}"}
                ).raise_for_status()
            pid = policy.json()["id"]
            report = client.post(f"/v1/policies/{pid}/simulate", headers=manager)
            report.raise_for_status()
            client.post(
                f"/v1/policies/{pid}/activate",
                headers=manager,
                json={"simulation_id": report.json()["id"], "acknowledge_impact": True},
            ).raise_for_status()

            def send(index):
                start = time.perf_counter()
                response = client.post(
                    "/v1/decisions", headers=collector, json={**event, "event_id": f"load-{index}"}
                )
                return (
                    response.status_code,
                    (time.perf_counter() - start) * 1000,
                    (response.json().get("allowed") is True),
                )

            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                results = list(pool.map(send, range(requests)))
            elapsed = time.perf_counter() - start
            statuses = Counter(str(row[0]) for row in results)
            if statuses != {"200": requests} or not all(row[2] for row in results):
                raise RuntimeError(f"Unexpected workload results: {dict(statuses)}")
            latencies = sorted(row[1] for row in results)

            def percentile(value):
                return round(latencies[min(len(latencies) - 1, int(len(latencies) * value))], 2)

            result = {
                "scope": "Synthetic loopback HTTP, SQLite, one service process; not a capacity SLA",
                "python": platform.python_version(),
                "platform": platform.system(),
                "requests": requests,
                "concurrency": concurrency,
                "http_statuses": dict(statuses),
                "duration_seconds": round(elapsed, 3),
                "requests_per_second": round(requests / elapsed, 2),
                "latency_ms": {
                    "p50": percentile(0.50),
                    "p95": percentile(0.95),
                    "p99": percentile(0.99),
                    "max": round(max(latencies), 2),
                },
            }
    timestamp = now()
    rows = [
        {
            "at": timestamp,
            "event": Event(event_id=str(i), service="replay", route="/items", subject="hot-user"),
        }
        for i in range(100000)
    ]
    start = time.perf_counter()
    report = simulate(
        Policy(name="Replay", service="replay", kind="rate_limit", threshold=50), rows
    )
    result["pure_replay"] = {
        "events": len(rows),
        "duration_seconds": round(time.perf_counter() - start, 3),
        "affected": report["affected_count"],
        "scope": "Policy engine only, no HTTP, persistence or efficacy inference",
    }
    assert report["affected_count"] == 99950
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.requests, args.concurrency)
    content = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
