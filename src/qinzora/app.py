import json
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .engine import regressions
from .errors import ApplicationError, require
from .explain import explain
from .models import (
    Activation,
    Event,
    Policy,
    RegressionRequest,
    TenantCreate,
    TenantUpdate,
)
from .repository import SQLiteRepository
from .service import (
    activate_policy,
    digest,
    record,
    revoke_policy,
    run_simulation,
)
from .service import (
    create_policy as create_policy_command,
)
from .store import Store


class BodyLimit:
    def __init__(self, app, maximum=1048576):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.maximum:
                return await JSONResponse({"detail": "Body exceeds 1 MiB"}, 413)(
                    scope, receive, send
                )
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


def create_app(db_path: str | None = None, admin_token: str | None = None):
    token = admin_token or os.environ.get("QINZORA_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise ValueError("QINZORA_ADMIN_TOKEN must contain at least 32 characters")
    store = Store(db_path or os.environ.get("QINZORA_DB", "data/qinzora.sqlite"))

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="Qinzora", version=__version__, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.store = store

    @app.exception_handler(ApplicationError)
    async def application_error(request, exc: ApplicationError):
        statuses = {
            "not_found": 404,
            "conflict": 409,
            "capacity_exceeded": 429,
            "replay_too_large": 413,
        }
        return JSONResponse({"detail": exc.message}, statuses[exc.code])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors normally echo user input. Do not echo credentials/payloads.
        return JSONResponse(
            {"detail": [{"loc": e["loc"], "type": e["type"]} for e in exc.errors()]}, 422
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        return JSONResponse({"detail": "Storage temporarily unavailable"}, 503)

    def bearer(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        value = authorization[7:]
        if len(value) > 512:
            raise HTTPException(401, "Invalid token")
        return value

    def admin(value: Annotated[str, Depends(bearer)]):
        if not secrets.compare_digest(value, token):
            raise HTTPException(401, "Invalid administrator token")

    def account(value: Annotated[str, Depends(bearer)]):
        key_digest = digest(value)
        with store.transaction() as db:
            row = db.execute(
                "SELECT keys.tenant,keys.role,tenants.enabled FROM keys "
                "JOIN tenants ON tenants.id=keys.tenant WHERE digest=?",
                (key_digest,),
            ).fetchone()
            if not row:
                raise HTTPException(401, "Invalid API key")
            if not row["enabled"]:
                raise HTTPException(403, "Account suspended")
            minute = int(time.time() // 60)
            db.execute("DELETE FROM request_limits WHERE minute<?", (minute - 1,))
            count = db.execute(
                "SELECT count FROM request_limits WHERE digest=? AND minute=?", (key_digest, minute)
            ).fetchone()
            if count and count[0] >= 600:
                raise HTTPException(
                    429, "Control API rate limit reached", headers={"Retry-After": "60"}
                )
            db.execute(
                "INSERT INTO request_limits VALUES (?,?,1) ON CONFLICT(digest,minute) "
                "DO UPDATE SET count=count+1",
                (key_digest, minute),
            )
            return dict(row)

    def manager(identity: Annotated[dict, Depends(account)]):
        if identity["role"] != "manager":
            raise HTTPException(403, "Manager key required")
        return identity

    Account = Annotated[dict, Depends(account)]
    Manager = Annotated[dict, Depends(manager)]

    @app.get("/healthz")
    def health():
        with store.transaction() as db:
            db.execute("SELECT 1")
        return {"status": "ok", "version": __version__}

    @app.post("/v1/admin/tenants", dependencies=[Depends(admin)], status_code=201)
    def create_tenant(body: TenantCreate):
        tenant = str(uuid4())
        manager_key, collector_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with store.transaction() as db:
            db.execute(
                "INSERT INTO tenants VALUES (?,?,1,?)", (tenant, body.name, body.event_limit)
            )
            for key, role in ((manager_key, "manager"), (collector_key, "collector")):
                db.execute("INSERT INTO keys VALUES (?,?,?)", (digest(key), tenant, role))
            Store.audit(db, tenant, "tenant.created", {"name": body.name})
        return {"id": tenant, "manager_key": manager_key, "collector_key": collector_key}

    @app.patch("/v1/admin/tenants/{tenant}", dependencies=[Depends(admin)])
    def update_tenant(tenant: str, body: TenantUpdate):
        with store.transaction() as db:
            require(db.execute("SELECT id FROM tenants WHERE id=?", (tenant,)).fetchone())
            db.execute("UPDATE tenants SET enabled=? WHERE id=?", (body.enabled, tenant))
            Store.audit(db, tenant, "tenant.enabled", {"enabled": body.enabled})
        return {"id": tenant, "enabled": body.enabled}

    @app.post("/v1/keys/rotate")
    def rotate_key(identity: Manager, role: str = Query(pattern="^(manager|collector)$")):
        new_key = secrets.token_urlsafe(32)
        with store.transaction() as db:
            db.execute("DELETE FROM keys WHERE tenant=? AND role=?", (identity["tenant"], role))
            db.execute(
                "INSERT INTO keys VALUES (?,?,?)", (digest(new_key), identity["tenant"], role)
            )
            Store.audit(db, identity["tenant"], "key.rotated", {"role": role})
        return {"key": new_key, "role": role}

    @app.post("/v1/policies", status_code=201)
    def create_policy(body: Policy, identity: Manager):
        with store.transaction() as db:
            return create_policy_command(SQLiteRepository(db, identity["tenant"]), body)

    @app.get("/v1/policies")
    def list_policies(identity: Manager):
        with store.transaction() as db:
            return SQLiteRepository(db, identity["tenant"]).policies()

    @app.post("/v1/events", status_code=201)
    def ingest(body: Event, identity: Account):
        with store.transaction() as db:
            return record(SQLiteRepository(db, identity["tenant"]), body, enforce=False)

    @app.post("/v1/decisions")
    def decision(body: Event, identity: Account):
        with store.transaction() as db:
            return record(SQLiteRepository(db, identity["tenant"]), body, enforce=True)

    @app.post("/v1/policies/{policy_id}/simulate")
    def replay_policy(policy_id: str, identity: Manager):
        with store.transaction() as db:
            return run_simulation(SQLiteRepository(db, identity["tenant"]), policy_id)

    @app.post("/v1/policies/{policy_id}/activate")
    def activate(policy_id: str, body: Activation, identity: Manager):
        with store.transaction() as db:
            return activate_policy(SQLiteRepository(db, identity["tenant"]), policy_id, body)

    @app.post("/v1/policies/{policy_id}/revoke")
    def revoke(policy_id: str, identity: Manager):
        with store.transaction() as db:
            return revoke_policy(SQLiteRepository(db, identity["tenant"]), policy_id)

    @app.get("/v1/incidents")
    def incidents(
        identity: Manager, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        with store.transaction() as db:
            return Store.listing(db, identity["tenant"], "incident", limit, offset)

    @app.get("/v1/audit")
    def audit(
        identity: Manager, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        with store.transaction() as db:
            return Store.listing(db, identity["tenant"], "audit", limit, offset)

    @app.post("/v1/incidents/{incident_id}/explain")
    def explain_incident(incident_id: str, identity: Manager):
        with store.transaction() as db:
            incident = require(Store.get(db, identity["tenant"], "incident", incident_id))
        return explain(
            incident, os.environ.get("QINZORA_OLLAMA_URL"), os.environ.get("QINZORA_OLLAMA_MODEL")
        )

    @app.get("/v1/simulations/{simulation_id}")
    def get_simulation(simulation_id: str, identity: Manager):
        with store.transaction() as db:
            return require(Store.get(db, identity["tenant"], "simulation", simulation_id))

    @app.get("/v1/events")
    def export_events(
        identity: Manager, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)
    ):
        with store.transaction() as db:
            rows = db.execute(
                "SELECT seq,received,data,result FROM events WHERE tenant=? "
                "AND seq>? ORDER BY seq LIMIT ?",
                (identity["tenant"], after, limit),
            ).fetchall()
            return {
                "items": [
                    {
                        "cursor": r["seq"],
                        "received_at": r["received"],
                        "event": json.loads(r["data"]),
                        "result": json.loads(r["result"]),
                    }
                    for r in rows
                ],
                "next_cursor": rows[-1]["seq"] if rows else after,
            }

    @app.post("/v1/regressions/check")
    def check_regressions(body: RegressionRequest, identity: Manager):
        try:
            findings = regressions(body.baseline, body.current)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with store.transaction() as db:
            Store.audit(db, identity["tenant"], "regressions.checked", {"findings": findings})
        return {
            "passed": not findings,
            "findings": findings,
            "scope": "Declared controls only; does not prove implementation correctness",
        }

    @app.get("/v1/usage")
    def usage(identity: Manager):
        with store.transaction() as db:
            row = db.execute(
                "SELECT event_limit,enabled FROM tenants WHERE id=?", (identity["tenant"],)
            ).fetchone()
            count = db.execute(
                "SELECT count(*) FROM events WHERE tenant=?", (identity["tenant"],)
            ).fetchone()[0]
            return {
                "retained_events": count,
                "event_limit": row["event_limit"],
                "enabled": bool(row["enabled"]),
            }

    return app
