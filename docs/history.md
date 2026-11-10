---
title: "Repository history and version counters"
description: "Functional changes, version notes and disclosure of administrative repository checkpoints."
---
# Repository history and version counters

## 0.4.1

Fixes decision-response correlation in both Python clients, strict verified authorization in continuity, and contract changes during primary/cache I/O. Adds an overall deadline for structured model calls and bounded, complete-response validation for advisory explanations. Rejects invalid administrator credentials at startup and malformed bearer values with an authentication error. Runtime, health and package metadata now report the same installed version.

Adds `qinzora backup`, a consistent SQLite snapshot command with overwrite protection, integrity verification, a bounded copy deadline and a restore/enforcement regression test. See the [quality review](quality-review.md) for reproduced defects, validation and remaining production work.

## 0.4.0

Adds experimental contract-based read continuity, its management API and scoped administration grants. Introduces English documentation and canonical explanation text, a published static documentation site, package metadata and validation workflows. Explanation field names/reason identifiers and deterministic access rules remain unchanged. Real-model continuity activation was verified in a bounded synthetic scenario; see [recorded evidence](validation/continuity-real-model.json).

The current documentation and release notes are English-only. Explicit action descriptions distinguish policy enforcement authority from continuity grants. Real-model validation records earlier abstentions and three completed trials after clarification; executor/runtime safeguards were retained.

The 0.3 line introduced Qinzora and combined persistence review, synchronous/asynchronous clients and model-based policy administration with replay and monitoring.

History contains administrative checkpoints explicitly requested to reach a particular commit count. They do not change code and do not represent development tasks, extra tests or work time.

Versions 0.3.1 through 0.3.21 change only version metadata relative to 0.3.0. Release notes disclose that they are administrative records without additional features. Commit/release counts are not quality, maturity or security metrics. Assess actual changes, tests and limits.
