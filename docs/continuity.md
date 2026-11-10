---
title: "Experimental contract-based continuity"
description: "This checkout adds a Python integration for read-only fallback when a primary dependency explicitly fails or times out. It is separate from policy enforcement, not a universal resilience layer."
---
# Experimental contract-based continuity

This checkout adds a Python integration for read-only fallback when a primary dependency explicitly fails or times out. It is separate from policy enforcement, not a universal resilience layer.

An operation contract specifies service, route, consumer, read/write effect, required fields, freshness and scalar rules. Host code pre-registers named cached sources. An account-scoped profile requires a bounded rehearsal. Activation binds profile, contracts and passing rehearsal by digest and TTL; HTTP management requires manager authority, impact acknowledgement and current digest.

`ContinuityRuntime` tries the primary operation once. After dependency unavailability it considers only an active compatible cached-read profile, checking authorization, same tenant, consumer, actual age, fields and scalar rules. It rechecks profile digest/expiry after loading. Writes are never replayed through cache or retried: timeout may occur after a remote commit. Changed configuration, expiry, revocation or bad evidence prevents fallback.

```text
qinzora demo --continuity
```

This uses real loopback HTTP for management, synthetic shipping/cache callbacks and an explicitly scripted planner. It checks allowed cached reads, refused unsafe responses and recovery. It does not establish provider availability or production resilience.

`--model INSTALLED_MODEL` attempts real Ollama inference without scripted substitution. Successful real-model continuity activation has **not** been established. Aggregate health signals exclude payloads/raw exceptions. Callbacks are trusted host code, not sandboxed. The host remains responsible for cache correctness, identity, authorization and acceptable stale data.
