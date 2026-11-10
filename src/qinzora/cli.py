import argparse
import asyncio
import json
import os
import secrets
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from .engine import regressions
from .models import RouteContract


def load_env():
    path = Path(".env")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("QINZORA_") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name, value.strip())


def main():
    parser = argparse.ArgumentParser(description="Qinzora policy service")
    parser.add_argument("--version", action="version", version=f"Qinzora {version('qinzora')}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Generate an ignored .env with a random admin token")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    demo = commands.add_parser("demo", help="Run an isolated reproducible demonstration")
    demo.add_argument("--live", action="store_true", help="Two processes with real HTTP")
    demo.add_argument("--present", action="store_true", help="Show integration verification steps")
    demo.add_argument(
        "--continuity", action="store_true", help="Rehearse and apply shipping fallback contracts"
    )
    demo.add_argument(
        "--model", help="Use real local Ollama inference for the continuity demonstration"
    )
    check = commands.add_parser(
        "check", help="Compare declared route protections; exit 1 on regression"
    )
    check.add_argument("baseline", type=Path)
    check.add_argument("current", type=Path)
    prune = commands.add_parser(
        "prune", help="Offline retention maintenance after exporting events"
    )
    prune.add_argument("--before", required=True)
    manage = commands.add_parser("manage", help="Propose an AI administration plan for one account")
    manage.add_argument("--config", type=Path, required=True)
    manage.add_argument(
        "--plan", help="Execute this previously proposed plan without new inference"
    )
    manage.add_argument(
        "--execute", action="store_true", help="Execute within configured authority"
    )
    watch = commands.add_parser("watch", help="Continuously administer changed API evidence")
    watch.add_argument("--config", type=Path, required=True)
    watch.add_argument("--execute", action="store_true")
    watch.add_argument("--interval", type=float, default=30)
    watch.add_argument("--model-timeout", type=float, default=60)
    args = parser.parse_args()
    if args.command == "demo":
        if args.model and not args.continuity:
            parser.error("--model requires --continuity")
        if args.continuity and (args.live or args.present):
            parser.error("--continuity cannot be combined with --live or --present")
    if args.command in ("manage", "watch"):
        import sqlite3

        from .administration.config import ManagementConfig, run_cycle, watch_service
        from .errors import ApplicationError
        from .providers import ModelUnavailable

        try:
            config = ManagementConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
            if args.command == "watch":

                async def watch_account():
                    await watch_service(
                        config,
                        asyncio.Event(),
                        execute=args.execute,
                        interval=args.interval,
                        model_timeout=args.model_timeout,
                        on_result=lambda row: print(json.dumps(row), flush=True),
                    )

                asyncio.run(watch_account())
                return
            result = asyncio.run(run_cycle(config, execute=args.execute, plan_id=args.plan))
        except KeyboardInterrupt:
            parser.exit(130, "Administration monitor stopped\n")
        except (OSError, ValueError):
            parser.exit(2, "Invalid management configuration or unavailable database/credentials\n")
        except (ApplicationError, ModelUnavailable) as exc:
            parser.exit(1, f"{exc}\n")
        except (sqlite3.Error, RuntimeError):
            parser.exit(1, "Management storage unavailable or unsupported schema\n")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "init":
        path = Path(".env")
        with path.open("x", encoding="utf-8") as file:
            file.write(
                f"QINZORA_ADMIN_TOKEN={secrets.token_urlsafe(48)}\nQINZORA_DB=data/qinzora.sqlite\n"
            )
        print("Created .env. Keep it private; credentials are not printed.")
    elif args.command == "serve":
        import uvicorn

        from .app import create_app

        load_env()
        uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)
    elif args.command == "demo":
        if args.continuity:
            from .continuity.demo import run_continuity_demo

            result = asyncio.run(run_continuity_demo(model=args.model))
        elif args.live or args.present:
            from .live_demo import run_live_demo

            def announce(name, detail):
                print(f"[OK] {name}: {json.dumps(detail, ensure_ascii=False)}", flush=True)

            result = run_live_demo(announce if args.present else None)
        else:
            from .demo import run_demo

            result = run_demo()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.continuity and not result["passed"]:
            raise SystemExit(1)
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

        store = Store(os.environ.get("QINZORA_DB", "data/qinzora.sqlite"))
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
