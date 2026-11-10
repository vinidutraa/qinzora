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

Stop the service and copy the database directory, including present WAL/SHM, or use SQLite's connection backup API. Test restoration. Copying an active database file alone does not establish consistency.

`python scripts/docker_smoke.py` builds and verifies policy behavior and restart persistence in an isolated Compose project. It removes only its own resources. A local daemon is required; CI runs this on Linux.
