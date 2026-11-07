import argparse
import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from .engine import regressions
from .models import RouteContract


def load_env():
    path = Path(".env")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("SENTINEL_") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name, value.strip())


def main():
    parser = argparse.ArgumentParser(description="API Sentinel policy service")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Generate an ignored .env with a random admin token")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    demo = commands.add_parser("demo", help="Run an isolated reproducible demonstration")
    demo.add_argument("--live", action="store_true", help="Two processes with real HTTP")
    demo.add_argument("--present", action="store_true", help="Show integration verification steps")
    check = commands.add_parser(
        "check", help="Compare declared route protections; exit 1 on regression"
    )
    check.add_argument("baseline", type=Path)
    check.add_argument("current", type=Path)
    prune = commands.add_parser(
        "prune", help="Offline retention maintenance after exporting events"
    )
    prune.add_argument("--before", required=True)
    args = parser.parse_args()
    if args.command == "init":
        path = Path(".env")
        with path.open("x", encoding="utf-8") as file:
            file.write(
                f"SENTINEL_ADMIN_TOKEN={secrets.token_urlsafe(48)}\n"
                "SENTINEL_DB=data/sentinel.sqlite\n"
            )
        print("Created .env. Keep it private; credentials are not printed.")
    elif args.command == "serve":
        import uvicorn

        from .app import create_app

        load_env()
        uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)
    elif args.command == "demo":
        if args.live or args.present:
            from .live_demo import run_live_demo

            def announce(name, detail):
                print(f"[OK] {name}: {json.dumps(detail, ensure_ascii=False)}", flush=True)

            result = run_live_demo(announce if args.present else None)
        else:
            from .demo import run_demo

            result = run_demo()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "check":
        baseline, current = [
            [RouteContract.model_validate(r) for r in json.loads(p.read_text(encoding="utf-8"))]
            for p in (args.baseline, args.current)
        ]
        findings = regressions(baseline, current)
        print(json.dumps({"passed": not findings, "findings": findings}, indent=2))
        raise SystemExit(1 if findings else 0)
    elif args.command == "prune":
        from .store import Store

        load_env()
        boundary = datetime.fromisoformat(args.before)
        if boundary.tzinfo is None:
            parser.error("--before requires an ISO datetime with timezone")
        from datetime import UTC

        store = Store(os.environ.get("SENTINEL_DB", "data/sentinel.sqlite"))
        with store.transaction() as db:
            count = db.execute(
                "DELETE FROM events WHERE received<?", (boundary.astimezone(UTC).isoformat(),)
            ).rowcount
        print(
            json.dumps(
                {
                    "pruned_events": count,
                    "note": "Replay and rate windows now contain only retained events",
                }
            )
        )


if __name__ == "__main__":
    main()
