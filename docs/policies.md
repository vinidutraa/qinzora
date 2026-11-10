---
title: "Policy evaluation"
description: "Candidates observe matching events without denying access. Routes use exact path-template equality or `*`, not arbitrary patterns. Services and opaque subjects are host-provided identifiers."
---
# Policy evaluation

Candidates observe matching events without denying access. Routes use exact path-template equality or `*`, not arbitrary patterns. Services and opaque subjects are host-provided identifiers.

## Tenant isolation

`tenant_isolation` checks that `actor_tenant` and `resource_tenant` are present and equal. Missing/mismatched context is a violation; an active policy can deny the attempt. Derive identity and ownership from trusted server state, not arbitrary request parameters. Matching tenants do not establish all permissions.

## Rate limiting

`rate_limit` counts attempts per `(service, route, subject)`, including denied attempts. `threshold` ranges from 1 to 100,000; `window_seconds` from 1 to 3,600. Counters use server receipt times and retained events. Pruning a recent window changes counts. This is not a globally distributed limiter.

## Response monitoring

`error_burst` monitors response status ≥400; `latency` monitors observed latency above its threshold. These concern completed responses and cannot block pre-operation requests. Sending the same attempt to `/events` and `/decisions` duplicates counts rather than updating a response.

## Historical simulation

`POST /v1/policies/{id}/simulate` evaluates a retained snapshot and returns its watermark, matched/affected counts, label breakdown and up to 100 affected event IDs. Replay errors above 100,000 retained events/account. Later events are absent; no real business operation is repeated.

`expected` labels (`legitimate`, `abusive`, `unknown`) come from the host. False-positive metrics describe that retained labeled sample only. Incorrect labels, small samples and old history do not establish future safety.

## Activation, expiry and revocation

Activate an enforceable kind using a matching simulation less than 15 minutes old, relevant events and `acknowledge_impact: true`. Manual activation requires operator review; legitimate impact is not automatically prohibited. AI administration separately checks configured replay criteria against fresh history.

One active policy's denial is sufficient. `ttl_seconds` is 1–86,400; expiry is checked during evaluation without a separate scheduler. Revocation stops enforcement. Recreate/review a candidate before reactivation. `allowed: true` only means no active Qinzora policy denied the attempt; retain host authorization.
