---
title: "HTTP API reference"
description: "The running instance exposes `/openapi.json` and interactive `/docs`. These generated contracts are authoritative for exact schemas, including experimental continuity routes. Version 0.4.0 uses Englis"
---
# HTTP API reference

The running instance exposes `/openapi.json` and interactive `/docs`. These generated contracts are authoritative for exact schemas, including experimental continuity routes. Version 0.4.0 uses English for canonical explanation text and model commentary instructions. Field names and reason identifiers remain unchanged; never parse human-readable prose as an authorization signal.

## Credentials

Send `Authorization: Bearer YOUR_KEY` from server-side code. The administrator token provisions accounts. A manager key manages one account; a collector key submits observations/decisions. Client keys are returned once and stored as hashes. Never ship keys to browsers.

| Method and route | Role | Purpose |
| --- | --- | --- |
| `GET /healthz` | Public | Readiness |
| `POST /v1/admin/tenants` | Administrator | Provision account |
| `PATCH /v1/admin/tenants/{id}` | Administrator | Enable/disable account |
| `POST /v1/policies` | Manager | Stage candidate |
| `GET /v1/policies` | Manager | List policies |
| `POST /v1/policies/{id}/simulate` | Manager | Historical replay |
| `POST /v1/policies/{id}/activate` | Manager | Activate reviewed simulation |
| `POST /v1/policies/{id}/revoke` | Manager | Revoke |
| `GET /v1/simulations/{id}` | Manager | Inspect stored replay |
| `POST /v1/events` | Collector | Record observation |
| `POST /v1/decisions` | Collector | Record attempt and decide |
| `GET /v1/events` | Manager | Cursor-based export |
| `GET /v1/incidents`, `GET /v1/audit` | Manager | Inspect evidence |
| `POST /v1/incidents/{id}/explain` | Manager | Canonical explanation and optional model text |
| `GET /v1/usage` | Manager | Retained event capacity |
| `POST /v1/regressions/check` | Manager | Compare declared route protection manifests |
| `POST /v1/keys/rotate?role=collector` | Manager | Replace role key; `manager` also supported |

Provisioning body: `{"name":"Example integration","event_limit":100000}`. Retain `manager_key` and `collector_key` separately. Integration accounts differ from the application's organizations in `actor_tenant` and `resource_tenant`.

Example event:

```json
{"event_id":"attempt-001","service":"documents","route":"/documents/{id}","method":"GET","subject":"opaque-user-001","actor_tenant":"company-a","resource_tenant":"company-b","expected":"unknown"}
```

The server assigns receipt time. `expected` is an application-provided replay label, not an AI prediction. Exclude tokens, bodies, query strings and personal identifiers. Reuse an event ID only for retries of the same request/mode. Do not submit one attempt to both endpoints.

## Bounds and export

Client keys: 600 requests/minute. Bodies: 1 MiB. Policies: 100/account. Replay: 100,000 retained events/account, otherwise an explicit error. Treat unavailability explicitly. Lists use `limit`/`offset`; event export uses `after` and `next_cursor`. Check OpenAPI for exact bounds.
