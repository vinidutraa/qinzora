---
title: "Getting started and installation"
description: "Install Qinzora and run its reproducible two-process HTTP demonstration."
---
# Getting started and installation

Use Python 3.12 or newer. Download a ZIP or clone the repository. Docker and a model provider are not needed for the basic demonstration. Internet access is needed for dependencies.

```sh
git clone https://github.com/vinidutraa/qinzora.git
cd qinzora
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps .
.venv\Scripts\qinzora.exe demo --present
```

Linux/macOS:

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/qinzora demo --present
```

The demo creates synthetic credentials and temporary storage. It starts independent processes, tests access, tenant violations, simulation, activation, rate limits, failure and recovery, and cleans up. Successful checks print `[OK]`; inspect the final `passed` field. `demo --live` returns JSON without presentation steps; `demo` uses an in-process test transport.

For another application, install a GitHub release wheel with `python -m pip install PATH_TO_WHEEL.whl`, or install downloaded source. Wheels contain runtime modules and CLI; repository scripts/examples are source-only. No PyPI publication is claimed.

## Persistent instance

Run the installed `qinzora init`, then `qinzora serve` in a dedicated working directory. The default database is `data/qinzora.sqlite`; the listener is `127.0.0.1:8765`. The generated `.env` contains a random administrator credential. Never commit it.

Open `http://127.0.0.1:8765/docs`. Continue with [provisioning](api.md) and [SDK integration](sdk.md). External exposure requires [deployment controls](deployment.md).
