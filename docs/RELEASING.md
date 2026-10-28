# Releasing

A release is made by pushing a version tag. The workflow `.github/workflows/release.yml` then builds the source and wheel distributions, runs the tests, checks that the wheel installs and contains the dashboard, creates a GitHub Release with the files attached, and, if enabled, publishes to PyPI.

## Steps for each release

1. Update `version` in `pyproject.toml` and `__version__` in `src/tahdeed/__init__.py`. They must match each other and the tag.
2. Move the entries under `Unreleased` in `CHANGELOG.md` to a new dated section.
3. Run `make lint`, `make test` and `make build-dist` locally.
4. Commit, then tag and push: `git tag v2.1.0 && git push origin main v2.1.0`.

The workflow fails early if the tag (without the leading `v`) differs from the version in `pyproject.toml`.

## What the owner must configure once

GitHub Release. No setup is needed. The workflow uses the built in `GITHUB_TOKEN` with `contents: write` for the release job only.

PyPI publishing is off until switched on, and the workflow does not fail when it is off.

1. Create the project on PyPI (or reserve the name `tahdeed`). Sign in at pypi.org, open "Publishing" and add a pending trusted publisher with these values: owner `hudasol`, repository `tahdeed`, workflow file `release.yml`, environment `pypi`.
2. In the GitHub repository, create an environment named `pypi` (Settings, Environments). Adding a required reviewer there gives a manual approval step before upload.
3. Set a repository variable `PYPI_PUBLISH` to `true` (Settings, Secrets and variables, Actions, Variables). Without it the `publish-pypi` job is skipped.

Trusted publishing uses short lived OpenID Connect tokens, so no PyPI API token is stored in GitHub.

## Data assets

The gazetteer and model are derived from OpenStreetMap and are not part of the Python distributions. Publish them as additional assets of the same release, together with a `MANIFEST.json` whose schema is described in [`DEPLOYMENT.md`](DEPLOYMENT.md), section 7. Under the ODbL the public must be able to obtain the derived database, so keep these assets available for as long as you offer a service that uses them. Users download and verify them with `tahdeed.fetch.fetch_data`.

## If a release fails

Fix the cause, delete the tag locally and on the remote only if no GitHub Release or PyPI upload was made from it, and tag again. A version uploaded to PyPI can never be reused: bump the patch version instead.
