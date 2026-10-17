# What needs Huda

Items that need an account, a click, a signature or a decision. Nothing here has been done on
Huda's behalf.

## Decisions

1. **PR #1** (`phase2-crosscity-bench`) stays open; merge when satisfied.
2. **Dubai POI trade off (T1).** The v2.1 model was kept because removing the training rows that
   hurt POI calibration triples address wrong city exposure (`docs/EVALUATION.md`, T1 section).
   Confirm this priority (fewer wrong city answers over better POI calibration) or ask for the POI
   tier calibration experiment described in `docs/PREDICTIONS.md`.

## Clicks and accounts

3. **Render demo (T5), optional.** Steps in `docs/DEPLOYMENT.md` section 5.6: create a GitHub
   Release with `region/gazetteer.sqlite.gz` and `region/ranker.npz` (built by
   `deploy/build_demo_region.sh`; the files are not committed), then New > Blueprint in Render and
   fill five variables. Needs a free Render account. Not deployed.

## Outreach

4. **Makani licence request (T4).** Draft in `docs/outreach/makani_request.md`. Fill the bracketed
   contact fields, check the current Dubai Municipality GIS Centre contact, and send it yourself.

## Data collection

5. **Human written test set.** The only realistic source of a fresh sealed set (`docs/SEALED2.md`).
   The kit is in `bench/human_kit/`; recruiting contributors and their consent are yours to handle.
   Aim for at least 400 rows, ideally 1,000, and keep the file outside the public repository until
   the frozen model has been run on it once.

## Compute

6. Training one model took about 1.5 hours on this machine while other jobs were running, so the
   second and third training seeds for T1 were not run. Rerun with an idle machine if the T1
   conclusion needs training variance: `tahdeed train --seed 1` (and 2) with the flags recorded in
   each model manifest, then `tahdeed ablate-poi`.
