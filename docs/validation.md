---
title: "Validation procedures"
description: "Reproduce automated tests, HTTP demonstrations, package checks and bounded real-model validation."
---
# Validation procedures

Use an isolated environment. CI tests Windows/Linux with Python 3.12 and 3.14; local results cover only the actual interpreter/environment.

```text
python -m pip install --require-hashes -r requirements-dev-lock.txt
python -m pip install --no-deps -e .
python -m ruff check src tests examples scripts
python -m ruff format --check src tests examples scripts
python -m pytest -q
python scripts/http_smoke.py
qinzora demo --present
qinzora demo --continuity
```

Coverage includes tenant boundaries, key roles, rate windows, replay/activation/expiry/revocation, idempotence, migrations, SDK failures, administration authority/transactions, monitor leases/checkpoints and continuity safeguards. Simulated providers do not prove inference quality. HTTP smoke/process demos exercise loopback services.

Optional environment-specific checks:

```text
python scripts/docker_smoke.py
python scripts/benchmark.py --help
python scripts/administration_smoke.py --model INSTALLED_MODEL
```

Docker requires an engine. Benchmarks describe only the tested host/workload. Abstention/rejection is not successful AI activation. Real-model continuity activation was verified in a bounded synthetic scenario; see [recorded evidence](validation/continuity-real-model.json). See [distribution](distribution.md) for package/docs builds. Passing tests are evidence for covered scenarios, not certification or complete protection.
