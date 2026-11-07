import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import now


class Store:
    """Local durable backend. A serialized transaction protects quotas and live windows."""

    def __init__(self, path: str):
        self.path = path

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES (1);
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    enabled INTEGER NOT NULL, event_limit INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS keys (
                    digest TEXT PRIMARY KEY, tenant TEXT NOT NULL, role TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL,
                    data TEXT NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS objects_scope ON objects(tenant, kind, created);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant TEXT NOT NULL, event_id TEXT NOT NULL, received TEXT NOT NULL,
                    service TEXT NOT NULL, route TEXT NOT NULL, subject TEXT NOT NULL,
                    data TEXT NOT NULL, result TEXT NOT NULL,
                    UNIQUE(tenant, event_id));
                CREATE INDEX IF NOT EXISTS event_scope
                    ON events(tenant, service, route, subject, received);
                CREATE TABLE IF NOT EXISTS request_limits (
                    digest TEXT NOT NULL, minute INTEGER NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(digest, minute));
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {r["name"] for r in db.execute("PRAGMA table_info(events)")}
            if "status_code" not in columns:
                db.execute("ALTER TABLE events ADD COLUMN status_code INTEGER NOT NULL DEFAULT 200")
                db.execute("UPDATE events SET status_code=json_extract(data,'$.status_code')")
            db.execute("DELETE FROM schema_version")
            db.execute("INSERT INTO schema_version VALUES (2)")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def put(db, tenant: str, kind: str, data: dict, object_id: str | None = None):
        object_id = object_id or str(uuid4())
        db.execute(
            "INSERT INTO objects VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (object_id, tenant, kind, json.dumps(data), now().isoformat()),
        )
        return object_id

    @staticmethod
    def get(db, tenant: str, kind: str, object_id: str):
        row = db.execute(
            "SELECT data FROM objects WHERE id=? AND tenant=? AND kind=?", (object_id, tenant, kind)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    @staticmethod
    def listing(db, tenant: str, kind: str, limit: int = 100, offset: int = 0):
        return [
            {"id": row["id"], **json.loads(row["data"])}
            for row in db.execute(
                "SELECT id,data FROM objects WHERE tenant=? AND kind=? "
                "ORDER BY created DESC,id LIMIT ? OFFSET ?",
                (tenant, kind, limit, offset),
            )
        ]

    @staticmethod
    def audit(db, tenant: str, action: str, detail: dict):
        Store.put(
            db, tenant, "audit", {"action": action, "detail": detail, "at": now().isoformat()}
        )
