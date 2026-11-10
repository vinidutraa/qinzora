---
title: "Security considerations"
description: "The host authenticates users, derives ownership from trusted server state, retains authorization, applies denied decisions and handles service failure. Browser tenant headers do not establish identity"
---
# Security considerations

The host authenticates users, derives ownership from trusted server state, retains authorization, applies denied decisions and handles service failure. Browser tenant headers do not establish identity.

Use separate administrator/manager/collector roles. Client keys are returned once, stored as hashes and immediately replaced by role rotation. Keep `.env`, databases, exports, provider credentials and management files private. Never log bearer tokens or put them in URLs. Retained metadata should use opaque subjects and route templates without sensitive bodies/queries.

Integration accounts differ from application tenants. Disabling an account stops its access. Request/policy/replay limits bound resources but do not replace an edge defense.

The SDK never implicitly allows unavailable/invalid decisions and never retries automatically. Preserve that behavior in hosts. Server receipt time governs rate windows; backward clock movement is rejected. Cancellation/timeout does not imply remote rollback.

AI text is not authorization. Administration independently checks authority, fresh replay and expiry. Schema-valid proposals can still be wrong. Continuity callbacks remain trusted integration code, not sandboxed plugins.

SQLite is single-instance; audit is not tamper-proof. Historical metrics describe retained labeled evidence. No complete protection, certification or arbitrary-load capacity is claimed. See the repository [security policy](https://github.com/vinidutraa/qinzora/blob/main/SECURITY.md); never post sensitive vulnerability details publicly.
