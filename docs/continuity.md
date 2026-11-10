---
title: "Experimental contract-based continuity"
description: "Rehearse and validate cached-read fallback contracts with bounded optional AI administration."
---
# Experimental contract-based continuity

This checkout adds a Python integration for read-only fallback when a primary dependency explicitly fails or times out. It is separate from policy enforcement, not a universal resilience layer.

An operation contract specifies service, route, consumer, read/write effect, required fields, freshness and scalar rules. Host code pre-registers named cached sources. An account-scoped profile requires a bounded rehearsal. Activation binds profile, contracts and passing rehearsal by digest and TTL; HTTP management requires manager authority, impact acknowledgement and current digest.

`ContinuityRuntime` tries the primary operation once. After dependency unavailability it considers only an active compatible cached-read profile, checking authorization, same tenant, consumer, actual age, fields and scalar rules. It rechecks profile digest/expiry after loading. Writes are never replayed through cache or retried: timeout may occur after a remote commit. Changed configuration, expiry, revocation or bad evidence prevents fallback.

```text
qinzora demo --continuity
```

This uses real loopback HTTP for management, synthetic shipping/cache callbacks and an explicitly scripted planner. It checks allowed cached reads, refused unsafe responses and recovery. It does not establish provider availability or production resilience.

`--model INSTALLED_MODEL` attempts real Ollama inference without scripted substitution. Real-model activation was verified on 2026-11-10 with local Ollama and `qwen3:4b-instruct` in three post-clarification trials. See [the recorded evidence](validation/continuity-real-model.json). Aggregate health signals exclude payloads/raw exceptions. Callbacks are trusted host code, not sandboxed. The host remains responsible for cache correctness, identity, authorization and acceptable stale data.


## Reproduce real-model validation

With Ollama running and the named model already installed:

```text
python scripts/continuity_smoke.py --model qwen3:4b-instruct --repeats 3 --output .artifacts/continuity-validation.json
```

The script records every trial, its actual actions, model rationale, model digest, environment and elapsed time. It does not retry until success, substitute scripted actions, bypass a rejected plan or mark abstention as success. Each trial uses an isolated account/database and real loopback HTTP management; the primary/cache adapters remain synthetic.

The first three-trial batch completed once and abstained twice. The model confused policy enforcement permission with the separately granted continuity actions. Clarifying the action descriptions and candidate/active distinction produced three completed trials in the recorded follow-up batch, without changing executor authority checks or runtime safeguards. These small samples are not reliability statistics. Rationale text still contains inaccurate interpretations of dependency health in some runs; it is advisory, and the deterministic executor/runtime independently validate actual behavior.

The passing trials verified: comparison of passing/failing rehearsals, activation, permitted cached read, rejection of cached writes, rejection of expired data, rejection of an invalid currency, and primary recovery. Continuous production operation and arbitrary provider/model behavior are not established by this demonstration.
