---
title: "Quality review and completion boundaries"
description: "Qinzora 0.4.1 review: reproduced defects, implemented corrections, recovery checks and remaining production evidence."
---
# Quality review and completion boundaries

Production audit: launchable with caveats for local evaluation and integration development; not a production certification or a claim of perfect software.

This review covers the Python service, SQLite adapter, synchronous/asynchronous clients, continuity runtime, AI provider boundaries, CLI, tests and distribution configuration. It does not assess arbitrary host applications, infrastructure or business adapters. Existing release artifacts remain immutable.

## Corrected defects

| Finding | Correction | Regression evidence |
| --- | --- | --- |
| Clients accepted any boolean decision without matching the request | Check the event identifier and observe/enforce mode against the serialized request | Both clients reject missing or mismatched identifiers/modes; real HTTP demos exercise valid responses |
| Service reported a historical version independently of package metadata | Read installed distribution metadata | Package, health and OpenAPI versions must agree |
| Invalid administrator configuration and non-ASCII bearer values could reach an unsafe string comparison | Require 32–512 visible ASCII characters for configured admin credentials; reject malformed bearer values with 401 | Invalid startup configuration creates no database; invalid header yields an authentication error |
| `.env` creation inherited the process's default file mode | Create credentials exclusively with POSIX mode `0600`; retain Windows directory ACL requirements | Initialization never prints or overwrites the token; POSIX CI checks file permissions |
| Truthy non-boolean authorization could invoke a primary adapter | Require literal `True` from the trusted host | Strings and integer 1 cannot execute an adapter |
| A primary call could overlap a changed contract and newly activated rehearsal | Recheck the registered contract before returning primary data and before/after loading fallback data | A changed contract cannot return a response validated under its old definition |
| Per-network-stage timeouts did not bound the structured model operation | Add an overall async deadline while retaining transport timeouts and cancellation propagation | An incomplete stream is cancelled and closed |
| Optional explanations loaded unbounded provider bodies and accepted incomplete output | Bound provider output to 256 KiB and require a completed response | Oversized, truncated and malformed responses retain the deterministic explanation |

Before corrections, newly added tests reproduced 28 failing cases across the client, version, credentials, continuity and structured-provider boundaries. Case counts describe test inputs, not 28 independently discovered vulnerabilities. Additional explanation and recovery tests cover their respective changes.

## Recovery delivery

`qinzora backup --output PATH` creates a new consistent SQLite snapshot through the backup API, including committed WAL contents. It checks the copied database, refuses overwrites and removes its own incomplete destination on failure. The copy has a 30-second deadline.

The restoration test recovers actual account keys, an active policy, events and an audit marker committed in WAL. A restored service then refuses a cross-tenant request. Separate tests cover existing destinations, missing sources, unsupported schemas, deadline cleanup and CLI output without credentials. Operator instructions are in [deployment and recovery](deployment.md#storage-and-recovery).

## Completion gates

### Local results for 0.4.1

- Full suite: **217 passed**, with one upstream test-transport deprecation warning; the previous baseline had 179 passing tests.
- Ruff check and formatting: passed for 63 Python files. Installed dependency consistency: passed.
- Independent-process HTTP smoke and scripted continuity: passed. Wheel and source distribution built successfully, including building the wheel from the sdist; Twine accepted both.
- Isolated installed wheel, executed outside the checkout: version 0.4.1, independent-process demonstration and backup command passed.
- Documentation: strict build and checks passed for 17 English pages.
- [Synthetic loopback benchmark](validation/benchmark-0.4.1.json): 400/400 HTTP 200 responses with 8 concurrent clients; 64.24 requests/second, p95 305.94 ms, maximum 996.64 ms. Pure in-memory replay of 100,000 events took 0.177 seconds. These are single-host Windows/Python 3.14.7 measurements, not a service-level promise or a comparison against another release.
- [Real local model check](validation/continuity-real-model-0.4.1.json): one trial completed all seven checks using `qwen3:4b-instruct`; the model invocation took 28.401 seconds. Primary/cache adapters remain synthetic; model rationale remains advisory and can misinterpret context.

The report records local evidence. Remote CI results must be checked independently against the published commit through [GitHub Actions](https://github.com/vinidutraa/qinzora/actions).

The release must pass the full automated suite, Ruff, the independent-process HTTP demonstration, synthetic continuity, dependency audit, strict documentation checks and clean package installation. GitHub must separately verify the exact published source on Windows/Linux with Python 3.12/3.14 and Docker. A previous run does not validate a new commit.

Real-model inference is a separate bounded check. The earlier [continuity evidence](validation/continuity-real-model.json) records abstentions as well as completed trials; the provider can still abstain or misinterpret advisory context. Cached responses remain subject to deterministic request-time checks. Neither model rationale nor rehearsal proves business correctness.

## What remains before a hosted SaaS

- **Distribution:** PyPI ownership and the trusted publisher require the account owner's authentication. A GitHub publishing workflow is not proof of package publication.
- **Real integration:** primary and cache adapters in the continuity demonstration are synthetic. Verify resource-level authorization, provenance, contract rules and recovery with the intended application's real adapters before enabling fallback there.
- **Capacity:** the SQLite deployment supports one service instance/worker and serialized writes. Establish latency, throughput and dataset-size targets for the intended workload. A small loopback benchmark is not an SLA or evidence for horizontal scaling.
- **Retention and quotas:** events have a retained-count limit and offline pruning. Audit records, incidents, plans and continuity configuration need a deliberate retention/size policy for a long-running hosted deployment. There is no unlimited-growth or multi-customer availability guarantee.
- **Operations:** provide TLS and perimeter connection/body/time limits, private administration access, monitoring/alert ownership, offsite encrypted backup retention and measured restore objectives in the actual deployment. The backup command is one component of that process.
- **Compatibility:** the current test transport emits an upstream Starlette/httpx deprecation warning. Dependency migration requires a reviewed, tested update; hiding the warning would not resolve it.

These are explicit completion boundaries, not features claimed by this release. For the reproducible portfolio backend, the core policy workflow and bounded continuity demonstration are implemented; a general production SaaS requires deployment-specific engineering and evidence.
