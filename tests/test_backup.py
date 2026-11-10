import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from test_api import policy, post_event

from qinzora.app import create_app
from qinzora.store import Store


def test_live_wal_backup_restores_keys_policies_events_and_enforcement(
    api, tenant, event, tmp_path
):
    client, admin = api
    created = policy(client, tenant, "tenant_isolation")
    post_event(client, tenant, event)
    replay = client.post(
        f"/v1/policies/{created}/simulate", headers=auth(tenant["manager_key"])
    ).json()
    activation = client.post(
        f"/v1/policies/{created}/activate",
        headers=auth(tenant["manager_key"]),
        json={"simulation_id": replay["id"], "acknowledge_impact": True},
    )
    assert activation.status_code == 200
    store = client.app.state.store
    destination = tmp_path / "restored.sqlite"
    # Keep the writer open so the marker remains committed in the live WAL.
    with closing(sqlite3.connect(store.path)) as writer:
        Store.put(writer, tenant["id"], "audit", {"marker": "committed-in-wal"}, "wal-marker")
        writer.commit()
        store.backup(destination)
    post_event(client, tenant, {**event, "event_id": "after-backup"})
    restored_store = Store(str(destination))
    with restored_store.transaction() as db:
        assert Store.get(db, tenant["id"], "audit", "wal-marker")["marker"] == "committed-in-wal"
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    with TestClient(create_app(str(destination), admin)) as restored:
        decision = post_event(
            restored,
            tenant,
            {**event, "event_id": "restore-probe", "resource_tenant": "another-company"},
            "decisions",
        )
        assert decision.status_code == 200 and decision.json()["allowed"] is False


def test_backup_never_replaces_existing_data_or_the_source(tmp_path):
    store = Store(str(tmp_path / "source.sqlite"))
    store.initialize()
    existing = tmp_path / "existing.sqlite"
    existing.write_bytes(b"keep this file")
    with pytest.raises(FileExistsError):
        store.backup(existing)
    assert existing.read_bytes() == b"keep this file"
    with pytest.raises(ValueError, match="differ"):
        store.backup(store.path)
    with store.transaction() as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 2


def test_missing_source_is_not_created_and_invalid_schema_is_not_copied(tmp_path):
    destination = tmp_path / "backup.sqlite"
    with pytest.raises(FileNotFoundError):
        Store(str(tmp_path / "missing.sqlite")).backup(destination)
    assert not list(tmp_path.iterdir())
    store = Store(str(tmp_path / "future.sqlite"))
    store.initialize()
    with store.transaction() as db:
        db.execute("UPDATE schema_version SET version=999")
    with pytest.raises(RuntimeError, match="Unsupported"):
        store.backup(destination)
    assert not destination.exists()


def test_backup_deadline_removes_its_incomplete_file(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "source.sqlite"))
    store.initialize()
    destination = tmp_path / "incomplete.sqlite"
    moments = iter([0, 31])
    monkeypatch.setattr("qinzora.store.time.monotonic", lambda: next(moments))
    with pytest.raises(TimeoutError):
        store.backup(destination)
    assert not destination.exists()


def test_backup_cli_loads_environment_without_disclosing_credentials(tmp_path):
    store = Store(str(tmp_path / "source.sqlite"))
    store.initialize()
    private_token = "test-private-token-never-print-it-123456789"
    (tmp_path / ".env").write_text(
        f"QINZORA_DB={store.path}\nQINZORA_ADMIN_TOKEN={private_token}\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-m", "qinzora.cli", "backup", "--output", "snapshot.sqlite"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("QINZORA_")},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["consistent"] is True
    assert private_token not in result.stdout + result.stderr
    assert (tmp_path / "snapshot.sqlite").is_file()
