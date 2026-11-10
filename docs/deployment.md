---
title: "Docker deployment and operations"
description: "Run one Qinzora instance with Docker Compose, persistent SQLite, backups and explicit access controls."
---
# Docker deployment and operations

After installation, run `qinzora init` and keep `.env` private. With Docker Engine and Compose:

```text
docker compose up --build -d
docker compose ps
docker compose logs
docker compose down
```

The image installs hash-locked dependencies, runs non-root and has a health check. Compose binds to loopback, uses a read-only root filesystem with explicit writable paths and retains SQLite in `qinzora-data`. `QINZORA_PORT` changes the host port. `down` without volume deletion preserves data.

Use one instance/worker. SQLite writes/replay serialize. Public exposure requires TLS, access controls, connection limits and administrator/readiness endpoint protection; these settings are not production certification.

## Storage and recovery

Export manager `GET /v1/events?after=CURSOR&limit=N`, following `next_cursor`, before pruning. Offline `qinzora prune --before TIME_WITH_TIMEZONE` deletes older events across accounts, changing replay/rate history; incidents and audit remain.

Create a consistent backup, including committed WAL data, while the service is running:

```text
qinzora backup --output backups/qinzora-snapshot.sqlite
```

Create the private `backups` directory first. The command reads `QINZORA_DB` (including `.env`), uses SQLite's backup API, checks the copied database and refuses an existing destination or the source path. It has a 30-second copy deadline; failures remove only the new incomplete snapshot. POSIX creation uses mode `0600`; Windows operators must protect the directory through ACLs. Backups contain account data and key hashes; store and transfer them privately.

To rehearse recovery, keep the original backup unchanged, copy it to a new empty directory and set `QINZORA_DB` to that copy. Use the compatible service version and original administrator configuration. Start the copy on a separate loopback port; verify `/healthz`, manager authentication, retained events and an actual deny decision. Rotate restored keys as appropriate: restoring an old database also restores its old key state.

For recovery of the normal service, stop it first and switch to the validated restored database in its new directory. Never combine a snapshot with WAL/SHM files from another database. Keep the pre-recovery directory until verification is complete. Automated tests exercise backup of committed WAL records, restoration and policy enforcement; they do not establish an offsite retention schedule or a recovery-time objective.

Alternatively, stop the service and copy its complete database directory, including present WAL/SHM. Copying an active database file alone does not establish consistency. See the [Python SQLite backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup).

`python scripts/docker_smoke.py` builds and verifies policy behavior and restart persistence in an isolated Compose project. It removes only its own resources. A local daemon is required; CI runs this on Linux.
