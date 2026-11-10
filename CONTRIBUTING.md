# Contributing to Qinzora

Use Python 3.12+. Report focused bugs/proposals with synthetic data and redacted logs. Preserve MIT licensing, tenant isolation, strict failure behavior, simulation gates, expiry, revocation and credential protection. Discuss contract, persistence or authority changes before broad redesigns.

Create a virtual environment, then use its Python:

```text
python -m pip install --require-hashes -r requirements-dev-lock.txt
python -m pip install --no-deps -e .
python -m pytest -q
python -m ruff check src tests examples scripts
python -m ruff format --check src tests examples scripts
python scripts/http_smoke.py
```

Add regression coverage for changed behavior. Never weaken safeguards to make a model proposal pass. Document compatibility/migration requirements. English is primary; maintain the Portuguese README and preserve technical Portuguese guides.

See [distribution instructions](docs/distribution.md), [security policy](SECURITY.md) and [code of conduct](CODE_OF_CONDUCT.md). Never commit secrets, databases, private exports or personal drafts. Pull requests should explain purpose, resulting behavior and actual checks.
