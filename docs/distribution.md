---
title: "Distribution and publication"
description: "Source installation and GitHub release wheels work independently of PyPI. No PyPI publication or live documentation deployment is implied by these files. A live PyPI JSON lookup returned 404 for `qinz"
---
# Distribution and publication

Source installation and GitHub release wheels work independently of PyPI. No PyPI publication or live documentation deployment is implied by these files. A live PyPI JSON lookup returned 404 for `qinzora` during preparation; this does not prove ownership, reservation or acceptance of that name.

## Build and inspect the package

Use an isolated environment and Python 3.12+:

```text
python -m pip install -r requirements-build.txt
python -m build
python -m twine check dist/*
```

Build produces a wheel and source distribution. Metadata includes MIT licensing, Python compatibility, keywords and repository links. Wheels contain runtime modules/CLI. Source distributions additionally contain tests, examples, scripts, documentation and dependency locks; private artifacts and credentials are excluded by an explicit include list.

Create a second clean virtual environment outside the repository. Install runtime dependencies from `requirements-lock.txt` with `--require-hashes`, then the built wheel with `--no-deps`. From a different working directory run its `qinzora --version`, `qinzora --help` and `qinzora demo`. Also build a wheel from the source archive to verify a complete sdist. Existing 0.3.21 release assets predate this checkout; do not overwrite them or describe them as containing later changes. Choose a new reviewed version for a future release.

## Documentation locally

```text
python -m pip install -r requirements-docs.txt
python -m mkdocs build --strict
python -m mkdocs serve
```

Open the address printed by MkDocs. The static output is `site/` (ignored by Git). Material supplies responsive navigation/search, accessible controls and Mermaid rendering. The site includes English and preserved Portuguese guides, canonical URLs, Open Graph metadata, sitemap and a permissive `robots.txt`, including OAI-SearchBot. This enables legitimate crawling; it does not guarantee indexing or recommendations.

The installed Material version announces maintenance ending on May 5, 2027. The site currently builds with the requested stack; review the upstream migration path before that date rather than assuming indefinite support. Documentation/build tools are separate from runtime dependencies.

## GitHub Pages

1. Review the intended public URL in `mkdocs.yml` and `docs/robots.txt`; change both if using another domain.
2. Merge reviewed files to `main`. Under **Settings → Pages**, select **GitHub Actions** as the build source.
3. Run the **Documentation** workflow on `main` with `deploy` checked. Ordinary pushes and pull requests build only. Review any environment approval requirement.
4. Verify the deployment job and actual HTTPS URL before announcing it. Check English/Portuguese navigation, code examples, mobile layout, search, `/sitemap.xml`, `/robots.txt`, canonical and Open Graph URLs.
5. Only after verification, add the live site to GitHub's homepage field and package metadata. Update canonical configuration before deploying a custom domain.

## Future PyPI Trusted Publishing

No publishing workflow is active and nothing here uploads to PyPI. Do not put API tokens in code. Follow [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) for the current account and project setup.

1. Confirm control of the PyPI account and the `qinzora` project name. A 404 lookup is insufficient; PyPI may reject or reserve a name. Resolve conflicts honestly before advertising an installation command.
2. Test on TestPyPI if desired, with a separately configured publisher and disposable environment. TestPyPI does not establish production PyPI ownership.
3. Choose a new immutable version in `pyproject.toml`, build/review both artifacts, run tests and inspect included files. Do not republish changed bytes under 0.3.21.
4. Create a protected GitHub environment named `pypi`; configure a PyPI trusted publisher for owner `vinidutraa`, repository `qinzora`, workflow filename `publish.yml`, environment `pypi`.
5. Review `publishing/publish.yml.example`, copy it to `.github/workflows/publish.yml`, and commit only when publishing is intended. Configure repository/environment approval restrictions before enabling it. The template is manual, main-only, with narrowly scoped OIDC permissions.
6. Trigger the workflow for the reviewed version. Verify PyPI metadata/artifact hashes and clean installation from PyPI before adding `pip install qinzora` as a working command.

See [adding a trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) and [using a publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/). Never claim a publication solely because a workflow file exists.

## GitHub discovery

The appropriate description is: “Open-source Python service for API security policy evaluation, rate limiting, tenant isolation, incident monitoring, and historical policy simulation.” Relevant topics: `python`, `api-security`, `rate-limiting`, `multi-tenancy`, `policy-engine`, `security-monitoring`, `fastapi`, `open-source`, `api-monitoring`.

Update these through repository **About → Edit** or authenticated `gh repo edit`. Keep descriptions aligned with actual functionality; do not use administrative commit/release counts as evidence of maturity.

## Post-publication checklist

- Verify CI against the exact public commit, not an older run.
- Verify public links, release version, hashes, wheel/sdist contents and clean installation.
- Confirm site HTTPS, canonical/OG image, sitemap/robots, search and mobile navigation.
- Confirm examples still work with the published artifact and documented limits remain visible.
- Keep credentials, private drafts and personal media outside Git.
- Present a reproducible demo and factual results; prepare LinkedIn copy separately and publish only when requested.
