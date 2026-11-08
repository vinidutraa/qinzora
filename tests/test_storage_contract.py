import sqlite3

import pytest
from pydantic import ValidationError

from qinzora.errors import ApplicationError
from qinzora.models import Policy
from qinzora.store import Store


@pytest.mark.parametrize("tenant,kind", [("other", "policy"), ("owner", "simulation")])
def test_object_collision_cannot_overwrite_another_scope(tmp_path, tenant, kind):
    store = Store(str(tmp_path / "scoped.sqlite"))
    store.initialize()
    with store.transaction() as db:
        Store.put(db, "owner", "policy", {"state": "candidate"}, "shared-id")
    with pytest.raises(ApplicationError):
        with store.transaction() as db:
            Store.put(db, tenant, kind, {"state": "active"}, "shared-id")
    with store.transaction() as db:
        assert Store.get(db, "owner", "policy", "shared-id") == {"state": "candidate"}
        assert Store.get(db, tenant, kind, "shared-id") is None
        Store.put(db, "owner", "policy", {"state": "revoked"}, "shared-id")
        assert Store.get(db, "owner", "policy", "shared-id") == {"state": "revoked"}


def test_newer_schema_is_not_silently_downgraded(tmp_path):
    store = Store(str(tmp_path / "future.sqlite"))
    store.initialize()
    with store.transaction() as db:
        db.execute("UPDATE schema_version SET version=99")
    with pytest.raises(RuntimeError, match="Unsupported database schema"):
        store.initialize()
    with store.transaction() as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 99


def test_failed_legacy_data_migration_rolls_back_schema_changes(tmp_path):
    store = Store(str(tmp_path / "legacy.sqlite"))
    store.initialize()
    with store.transaction() as db:
        db.execute("ALTER TABLE events DROP COLUMN status_code")
        db.execute("UPDATE schema_version SET version=1")
        db.execute(
            "INSERT INTO events(tenant,event_id,received,service,route,subject,data,result) "
            "VALUES ('t','e','2026-01-01','s','/r','u','invalid-json','{}')"
        )
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()
    with store.transaction() as db:
        assert "status_code" not in {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 1


@pytest.mark.parametrize("route", ["/items?secret=1", "/items#token"])
def test_policy_rejects_routes_that_cannot_match_event_contract(route):
    with pytest.raises(ValidationError):
        Policy(name="test", service="s", kind="rate_limit", route=route)
