import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from .errors import ApplicationError
from .models import now


class Store:
    """Local durable backend. A serialized transaction protects quotas and live windows."""

    def __init__(self, path: str):
        self.path = path

    def backup(self, destination: str | Path, *, timeout: float = 30) -> Path:
        """Create a consistent standalone SQLite snapshot without replacing any file."""
        if not 0 < timeout <= 3600:
            raise ValueError("Backup timeout must be in (0, 3600]")
        source, target = Path(self.path).resolve(strict=True), Path(destination).resolve()
        if source == target:
            raise ValueError("Backup destination must differ from the source")
        deadline = time.monotonic() + timeout

        def progress(status, remaining, total):
            if time.monotonic() >= deadline:
                raise TimeoutError("Backup deadline exceeded")

        # Read-only prevents accidental creation or migration of the source.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            versions = original.execute("SELECT version FROM schema_version").fetchall()
            if len(versions) != 1 or versions[0][0] not in (1, 2):
                raise RuntimeError("Unsupported database schema")
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            try:
                with closing(sqlite3.connect(target)) as copy:
                    original.backup(copy, pages=256, progress=progress, sleep=0.01)
                    if copy.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise RuntimeError("Backup integrity check failed")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        return target

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Journal configuration must happen outside the migration transaction.
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        with self.transaction() as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            if exists:
                versions = [row[0] for row in db.execute("SELECT version FROM schema_version")]
                if len(versions) != 1 or versions[0] not in (1, 2):
                    raise RuntimeError(
                        "Unsupported database schema; use a compatible service version"
                    )
            schema = """
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
                CREATE INDEX IF NOT EXISTS event_ingestion ON events(tenant, seq);
                CREATE TABLE IF NOT EXISTS request_limits (
                    digest TEXT NOT NULL, minute INTEGER NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(digest, minute));
            """
            # executescript implicitly commits. Execute the controlled DDL individually
            # so schema changes and data migration roll back together on failure.
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
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
        cursor = db.execute(
            "INSERT INTO objects VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data "
            "WHERE objects.tenant=excluded.tenant AND objects.kind=excluded.kind",
            (object_id, tenant, kind, json.dumps(data), now().isoformat()),
        )
        if cursor.rowcount != 1:
            raise ApplicationError("conflict", "Object identifier is already in use")
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
