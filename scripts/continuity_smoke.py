"""Exercise real model inference; preserve every trial, including abstentions."""

import argparse
import asyncio
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from qinzora.continuity.demo import run_continuity_demo
from qinzora.errors import ApplicationError
from qinzora.providers import ModelUnavailable


async def run(model, base_url, repeats):
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        response = await client.get(base_url.rstrip("/") + "/api/tags")
        response.raise_for_status()
        installed = next(
            (item for item in response.json()["models"] if item["name"] == model), None
        )
        if installed is None:
            raise ValueError("The requested model is not installed at this Ollama endpoint")
    started = time.perf_counter()
    trials = []
    for _ in range(repeats):
        try:
            trial = await run_continuity_demo(model=model, base_url=base_url)
        except (ApplicationError, ModelUnavailable, TimeoutError) as error:
            trial = {
                "passed": False,
                "inference": "real Ollama",
                "model": model,
                "error": type(error).__name__,
                "reason": str(error),
            }
        trials.append(trial)
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "model": model,
        "model_digest": installed["digest"],
        "duration_seconds": round(time.perf_counter() - started, 3),
        "passed": all(trial["passed"] for trial in trials),
        "trials": trials,
        "scope": "Real local inference and loopback HTTP; synthetic shipping/cache adapters. "
        "This is a bounded demonstration, not a production reliability guarantee.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run(args.model, args.base_url, args.repeats))
    content = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
