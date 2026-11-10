---
title: "CLI reference"
description: "Qinzora commands for demonstrations, serving, policy administration and maintenance."
---
# CLI reference

Use `qinzora --help` and per-command `--help` for flags.

| Command | Behavior |
| --- | --- |
| `qinzora --version` | Installed distribution version |
| `qinzora init` | Create private `.env`; refuse overwrite |
| `qinzora serve --host 127.0.0.1 --port 8765` | Start one worker |
| `qinzora demo` | In-process synthetic scenario, JSON |
| `qinzora demo --live` | Independent processes, real HTTP |
| `qinzora demo --present` | Real HTTP with terminal steps |
| `qinzora demo --continuity` | Experimental read-fallback rehearsal, scripted planner |
| `qinzora demo --continuity --model MODEL` | Attempt real Ollama inference, no scripted substitution |
| `qinzora check BASELINE.json CURRENT.json` | Compare declared protections; exit 1 on regression |
| `qinzora manage --config FILE.json` | Persist draft plan |
| `qinzora manage --config FILE.json --plan ID --execute` | Execute that plan within authority |
| `qinzora watch --config FILE.json --execute --interval 30 --model-timeout 60` | Monitor changes and administer within authority |
| `qinzora prune --before 2026-01-01T00:00:00+00:00` | Offline deletion of older events across accounts |
| `qinzora backup --output backups/snapshot.sqlite` | Consistent SQLite backup; refuse overwrite and validate the snapshot |

Export before pruning and stop the normal service for offline maintenance. Pruning changes replay/rate history; audit and incidents remain. Timestamps require a timezone.

Create the private destination directory before backing up. A live backup uses SQLite's backup API; [rehearse restoration](deployment.md#storage-and-recovery) before relying on it for recovery.

Regression manifests declare `method`, `path`, `authenticated`, `tenant_isolation`. Comparing `examples/baseline.json` with `examples/regression.json` intentionally exits 1; comparing baseline with itself exits 0. The checker does not inspect arbitrary code or prove authorization works.

Management configuration/database access are trusted local operator capabilities. `--execute` cannot override `allow_enforce: false`. Stopping a monitor does not undo committed actions or guarantee remote cancellation.
