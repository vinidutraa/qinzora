"""SQLite adapter. The caller owns the transaction; this adapter never commits."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .errors import ApplicationError, require
from .models import Event
from .store import Store


@contextmanager
def account_transaction(store: Store, tenant: str) -> Iterator["SQLiteRepository"]:
    """Bind administration to an existing enabled account on every transaction."""
    with store.transaction() as db:
        row = require(db.execute("SELECT enabled FROM tenants WHERE id=?", (tenant,)).fetchone())
        if not row["enabled"]:
            raise ApplicationError("conflict", "Account is disabled")
        yield SQLiteRepository(db, tenant)


class SQLiteRepository:
    def __init__(self, db: sqlite3.Connection, tenant: str) -> None:
        self.db = db
        self.tenant = tenant

    def previous_event(self, event_id: str) -> tuple[Event, dict[str, Any]] | None:
        row = self.db.execute(
            "SELECT data,result FROM events WHERE tenant=? AND event_id=?", (self.tenant, event_id)
        ).fetchone()
        return (Event.model_validate_json(row["data"]), json.loads(row["result"])) if row else None

    def event_count(self) -> int:
        return self.db.execute(
            "SELECT count(*) FROM events WHERE tenant=?", (self.tenant,)
        ).fetchone()[0]

    def event_limit(self) -> int:
        row = require(
            self.db.execute("SELECT event_limit FROM tenants WHERE id=?", (self.tenant,)).fetchone()
        )
        return row["event_limit"]

    def policies(self) -> list[dict[str, Any]]:
        return Store.listing(self.db, self.tenant, "policy", limit=1000)

    def latest_timestamp(self) -> datetime | None:
        row = self.db.execute(
            "SELECT received FROM events WHERE tenant=? ORDER BY seq DESC LIMIT 1", (self.tenant,)
        ).fetchone()
        return datetime.fromisoformat(row["received"]) if row else None

    def counts(self, event: Event, start: datetime, end: datetime) -> tuple[int, int]:
        row = self.db.execute(
            "SELECT count(*),coalesce(sum(status_code>=400),0) FROM events "
            "WHERE tenant=? AND service=? AND route=? AND subject=? "
            "AND received>? AND received<=?",
            (
                self.tenant,
                event.service,
                event.route,
                event.subject,
                start.isoformat(),
                end.isoformat(),
            ),
        ).fetchone()
        return row[0], row[1]

    def append_event(self, event: Event, timestamp: datetime, result: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(tenant,event_id,received,service,route,subject,"
            "status_code,data,result) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                self.tenant,
                event.event_id,
                timestamp.isoformat(),
                event.service,
                event.route,
                event.subject,
                event.status_code,
                event.model_dump_json(),
                json.dumps(result),
            ),
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "event": Event.model_validate_json(row["data"]),
                "at": datetime.fromisoformat(row["received"]),
                "seq": row["seq"],
            }
            for row in self.db.execute(
                "SELECT seq,data,received FROM events WHERE tenant=? ORDER BY seq", (self.tenant,)
            )
        ]

    def get(self, kind: str, object_id: str) -> dict[str, Any] | None:
        return Store.get(self.db, self.tenant, kind, object_id)

    def put(self, kind: str, data: dict[str, Any], object_id: str | None = None) -> str:
        return Store.put(self.db, self.tenant, kind, data, object_id)

    def audit(self, action: str, detail: dict[str, Any]) -> None:
        Store.audit(self.db, self.tenant, action, detail)
