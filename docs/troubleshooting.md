---
title: "Troubleshooting"
description: "Diagnose configuration, authorization, simulation, provider and installation failures."
---
# Troubleshooting

| Symptom | Check |
| --- | --- |
| Command missing | Use virtual environment executable; install package after dependencies. |
| `init` refuses overwrite | Existing private configuration is deliberately preserved. |
| 401/403 | Correct role, enabled account, rotated key; never print secrets. |
| Decision unavailable | Readiness, URL and timeout; keep the operation unavailable. |
| Candidate does not deny | Candidate/expired/revoked state, matching route and enforceable kind. |
| Activation rejected | Matching simulation, relevant events, age under 15 minutes and acknowledgement. |
| Unexpected rate count | Denied attempts count; avoid duplicate observation/decision submissions. |
| Replay fails | Maximum 100,000 retained events/account; export and plan retention. |
| AI fails/abstains | Provider, installed model, schema support and authority; do not weaken grants for a demo. |
| Monitor stops | Inspect JSON statuses and storage/model errors. |
| Docker unavailable | CLI, daemon, Compose, port and private `.env`. |
| PyPI installation fails | No PyPI release is claimed; install source or GitHub release wheel. |

The demo uses temporary storage, not your normal database. Report bugs with synthetic reproductions, installed version, Python/OS and redacted output.
