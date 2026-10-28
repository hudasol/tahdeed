# Contributing

Thank you for considering a contribution. This guide covers setup, the checks a change must pass, and how experiments are recorded.

## Setup

Python 3.11 or newer is required.

```bash
git clone https://github.com/hudasol/tahdeed.git
cd tahdeed
python -m venv .venv && source .venv/bin/activate
make install            # pip install -e ".[dev]" and the pre-commit hooks
```

The tests use a small committed fixture (`tests/fixtures/mini.sqlite`, an OpenStreetMap excerpt around Al Khalidiyah). The full gazetteer and model are not needed for the test suite. To build them, see the README and `make build-data` and `make train`.

## Checks

Run these before opening a pull request. Continuous integration runs the same commands.

```bash
make lint      # ruff check and ruff format --check, then mypy
make test      # pytest with a coverage gate of 70%
make format    # apply ruff formatting
```

Generated documents (`docs/EVALUATION.md`, `docs/EDGE_PROPOSAL.md`, and the result blocks in `README.md` and `docs/MODEL_CARD.md`) are rendered from result files by scripts in `scripts/`. Edit the script, not the output, then run it again. Continuous integration fails if a generated file differs from what its script renders. The same applies to `bench/`: `python scripts/check_bench_drift.py` must pass.

## Changes

- Keep each commit to one logical change, with a message that says what changed and why.
- Add or update tests with the code. Bug fixes should include a test that fails without the fix.
- Update `CHANGELOG.md` under `Unreleased` for any change a user would notice.
- Do not commit data derived from OpenStreetMap (the gazetteer, models trained on it, raw extracts). They are ODbL licensed and are built locally or published as release assets.
- Do not commit personal data. Query examples in tests and documents must be synthetic or taken from public map data.

## Running an experiment

Experiments that change the resolver or its evaluation follow a pre-registration rule, so that results cannot be shaped after the fact.

1. Write the hypothesis and the predicted numbers in `docs/PREDICTIONS.md` and commit them. Name the split that will be used, the metric, and the threshold that would count as a hit.
2. Run the experiment on the dev split only. The sealed split is for final reports, and each sealed run is recorded; do not use it to choose between options. `docs/SEALED2.md` explains why a second sealed set does not exist yet.
3. Write the result next to each prediction in the same table, whether it is a hit or a miss. Do not edit the prediction text.
4. Commit the result files (`docs/*.json`) and regenerate the documents that read them (`python scripts/make_evaluation_md.py`, `python scripts/make_results_blocks.py`).
5. If the experiment changes a number quoted in the README or the model card, that number must come from the generated block, not from hand editing.

The full reproduction sequence is in `scripts/reproduce.sh`.

## Reporting problems

Use the issue templates for bugs and feature requests. For security problems, follow [`SECURITY.md`](SECURITY.md) instead of opening a public issue.

By contributing you agree that your contribution is licensed under the MIT licence of this repository, and you agree to follow the [code of conduct](CODE_OF_CONDUCT.md).
