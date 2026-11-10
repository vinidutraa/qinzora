---
title: "Optional AI features"
description: "No model is required for policy evaluation or the standard demonstrations."
---
# Optional AI features

No model is required for policy evaluation or the standard demonstrations.

## Incident commentary

Set `QINZORA_OLLAMA_URL` and `QINZORA_OLLAMA_MODEL`, then call manager `POST /v1/incidents/{id}/explain`. Canonical `explanation` remains; optional text appears separately in `model_explanation`. Known categories, fixed meanings and counts are sent, not raw event identities or payloads. Inference timeout is 60 seconds, connection timeout 2 seconds. Commentary can be wrong and cannot activate policies.

## Bounded policy administration

`qinzora.administration` lets a model propose a typed plan. A separate executor validates authority and performs actions. Schema compliance alone does not authorize execution. The model receives no database connection, executable functions or operating-system access.

Copy `examples/management.json`, configuring an existing database, provisioned account and installed model. Keep provider secrets in environment variables via `api_key_env`, not JSON or Git.

```text
qinzora manage --config FILE.json
qinzora manage --config FILE.json --plan RETURNED_ID --execute
```

The example defaults to `allow_enforce: false`. Enforcement requires explicit service/route scopes, TTL and rate bounds. Plans contain at most five actions: `stage_policy`, `enforce_policy`, `revoke_policy`; experimental continuity actions require explicit profile grants. Empty plans are valid abstentions.

Before enforcement, the executor replays current history. Defaults require legitimate/abusive evidence, affected abuse, no affected unknown labels and zero observed false positives. Labels come from the host, not the model. Plans normally expire after five minutes; scope/policy/authority changes can invalidate them. Database actions commit atomically; repeated completed execution returns stored results. Rollback does not cover external operations.

`qinzora watch --config FILE.json --execute` persists checkpoints and a per-account lease, avoids repeated inference on unchanged evidence and backs off on model failure. It does not provide distributed HA or guarantee renewal of expired policies.

## Providers and data

`StructuredModel` defines async `generate(system, context, result_type)`. `HTTPStructuredModel` supports `ollama` and `chat_completions` with JSON Schema. Chat URLs include the provider prefix (e.g. `/v1`). Endpoints/models are trusted operator configuration, never model-selected. Invalid, incomplete or oversized responses raise `ModelUnavailable`. Response envelopes are bounded to 256 KiB; no implicit retries/fallback occur.

Administration sends configuration, authority and aggregate evidence, not raw identities, tenant values, bodies or queries. Service/route/policy names and IDs still disclose application metadata. Custom contexts are not automatically scrubbed. Review the provider destination and use TLS remotely.

## Verification

Controlled provider tests use simulated responses and do not establish real inference quality. For a real local model with temporary storage and real HTTP:

```text
python scripts/administration_smoke.py --model INSTALLED_MODEL
python scripts/administration_smoke.py --model INSTALLED_MODEL --watch
```

Abstention/rejected execution is not successful activation. Results depend on provider/model/environment. Successful real-model continuity activation remains unverified; its default planner is explicitly scripted.
