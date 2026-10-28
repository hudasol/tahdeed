# Design notes

This document records how the resolver reached its current design: which limits were found in version 1.0, what caused each one, what was changed, and what the change measured. It is a history of engineering decisions, not a specification. For the pipeline as it stands, read [`METHODOLOGY.md`](METHODOLOGY.md). For current numbers, read [`EVALUATION.md`](EVALUATION.md). The predictions made before each measurement are in [`PREDICTIONS.md`](PREDICTIONS.md).

Work after version 1.0 was organised in five development rounds. Each round started from a list of known problems, made a fixed set of changes, and re measured on the dev split. The sealed split was used once for the 1.0 baseline (through the old combined test set) and once at the end.

## 1. Limits found in version 1.0

Two diagnostic scripts were run on version 1.0 (2,500 hole queries and 400 consonant variant queries). The table gives the observed limit, its measured cause, and the direction taken.

| Limit | Measured cause | Direction |
|---|---|---|
| Queries are synthetic and the noise model is ours | One author wrote both the query generator and the matcher, so the matcher was tuned to the generator. No real user text exists in the repository. | Add a second, independent generator built from the Arabic names, a hand written set, and a sealed split. Report the gap between generators. |
| Truth is OpenStreetMap, and Dubai is only evaluated on POI queries | OSM has almost no structured Dubai addresses. Modelling cannot fix this. | Keep Dubai in a separate benchmark and label what it measures. Never present POI success as address success. |
| 29% of confident answers were wrong when the true address was absent | Prior shift. The ranker was trained with 15% hidden truth queries, so it learned that the same street and the same house number is almost always right. With the truth absent it returned the same street name in another district or city, and interpolations of 100 to 170 m scored as "within 50 m". 223 of 330 wrong confident answers had the right street name and number in the wrong district. | Train on a hole mixture. Add district conflict, key ambiguity and "number absent from this street" features. Cap interpolation confidence. Report a sensitivity curve over the hole rate. |
| Consonant transliteration variants resolved at 45% | Evidence loss and blocked retrieval. Keys shorter than four characters were left out of the coarse and fuzzy indices, so `Al Fagr` could not find `Al Fajr`. Greedy span selection let a short exact partial block the fuzzy full name span. Digraph classes were handled in the key but not in the retrieval index. | Generate coarse and fuzzy spans for all n grams, allow exact coarse matches for short keys, score spans by explained mass, add a key ambiguity feature. |
| Short skeleton collisions | Skeletons drop vowels, so three consonant keys such as `db` collide across unrelated names (Dubai, Dibba, Al Doob). No feature told the ranker how ambiguous a key was. | Add key ambiguity counts and a surface similarity feature on the unstripped string. |
| The reported radius was misleading | The 90% radius was fitted only on answers that were correct at their tier, so it described extent, not risk. A reader could take "within 2.5 km" as a guarantee. | Add calibrated heads for P(within 50 m), P(within 200 m) and P(within 1 km). Keep the radius and label it as conditional. |
| Predictions were not recorded in advance | Development and evaluation shared test districts. | Split test districts three ways: dev for iteration, sealed for the baseline and the final report. Write predictions before each run. |
| Operations: pickle model, 420 MB resident, 7 s load, 2 cores | Pickle executes code on load, scikit-learn was needed for inference, and the gazetteer indices were Python dicts. | Export the trees to a plain array format, drop scikit-learn at inference, add checksums and version stamps. |

## 2. Design rules that followed

1. Evidence is never discarded silently. Every lossy transform (vowel dropping, class merging) is paired with a feature that records how lossy it was, such as key length, ambiguity or match view.
2. The ranker is trained on the distribution it will be deployed on. The hole rate, language mix and noise are parameters of the training mixture, and sensitivity to them is reported.
3. Two independent query generators. Anything tuned against one is judged on the other.
4. Abstaining is preferred to a confident wrong point. The costs are explicit in the decision policy.
5. Inference depends only on NumPy and RapidFuzz, uses no pickle, uses versioned artefacts, and is deterministic.

The system is organised in three planes. The data plane builds a versioned gazetteer (SQLite, checksum, provenance record) from an OSM extract. The resolution plane normalises text, parses it, matches names, generates candidates at several tiers, ranks them and applies the decision policy. The serving plane exposes the CLI, the HTTP API, the dashboard, the audit log and the registry adapter interface. An evaluation plane sits beside them with both query generators, the hand written set, the splits and the metrics.

## 3. Development round 1: evaluation validity, calibration under shift, retrieval recall

Problems found

- The headline precision of 98.1% was measured with no holes. With a 15% hole mix in training the ranker learned that a matching street and number is nearly always right. Removing the truth dropped precision to 71%.
- The district check was computed per street (does this street exist in the district) and not per candidate (is this address in the district), so the feature that mattered did not exist.
- Interpolated points carried too much confidence for the tier.
- Retrieval, not ranking, capped recall: 95 of 120 failed consonant variant queries found a street span but chose the wrong one. Three independent causes: short key exclusion, greedy span selection that let a short exact partial block the full name span, and single view retrieval.
- The ranker had no feature for key ambiguity or for which retrieval view produced a match.
- No sealed split, no confidence intervals, no recorded predictions.

Changes

- Split the test districts into dev and sealed. Record predictions before each run.
- Keep consonant class sibling keys alongside exact keys. Allow three letter keys with a cap on weak evidence. Generate fuzzy spans for all n grams.
- Select spans by dynamic programming over explained mass (weighted interval scheduling) instead of greedily.
- Add candidate level features: exact key, area match, city match, alternate street name, and street, POI and area ambiguity.
- Offer interpolation also when every exact number hit lies outside the named district.
- Train and calibrate on a 30% hole mixture. Report hole sensitivity at 0, 15, 30, 50 and 100%.
- Add calibrated heads for P(within 200 m) and P(within 1 km).
- Add bootstrap 95% confidence intervals to headline metrics.

Measured effect (dev split)

| Metric | Version 1.0 | After round 1 |
|---|---|---|
| Resolved share / precision at 50 m, no holes | 61.9% / 98.1% | 64.5% / 98.2% |
| Forced top 1 within 50 m | 64.6% | 67.4% (CI 66.2 to 68.6%) |
| Precision of resolved answers with holes | 71.0% | 83.7% |
| Consonant variant top 1 within 50 m | 45% | 49.8% |
| ECE of P(within 50 m), P(within 200 m), P(within 1 km) | 0.020, n/a, n/a | 0.021, 0.019, 0.015 |
| Median and p95 latency | 5 ms and 7 ms | 8.7 ms and 15.3 ms |

The first retrain after these changes lowered the resolved share from 62% to 36%. Sampling the failures found three causes: a house number written before a street type word was absorbed into the street name span, bare numbers at span edges produced junk keys, and a Latin street type that follows the name let a longer unrelated street outcompete the correct one. Each received a targeted fix and a unit test. Three of seven predictions missed or nearly missed.

Carried forward: an independent second generator, latency and memory tracking, and a hand written query set.

## 4. Development round 2: reliability, security and deployability

Problems found

- The model artefact was a pickle, which runs code on load, and scikit-learn was a heavy dependency for four small tree ensembles.
- Nothing tied the gazetteer, the model and the code together. A model trained on one feature set could silently score another. This had already happened once during development, as a 57 versus 50 feature mismatch.
- The dashboard claimed to work offline but loaded Leaflet and fonts from public CDNs.
- Input was trusted. The API truncated at 500 characters, but nothing was tested against hostile Unicode, long digit strings, bidirectional control characters or pathological repetition.
- There was no per query time budget.
- There were no structured logs, and a naive log would have written home addresses to disk.
- A missing model file silently fell back to the uncalibrated heuristic without saying so, so a downstream system could treat an uncalibrated 0.8 as a calibrated probability.
- Packaging: no container, no pinned dependencies, no coverage gate, no vulnerability audit, one Python version in CI, single process batch mode.
- The HTTP layer had no security headers, no body size limit and no authentication hook.

Changes

- Export the four heads to a `.npz` file with an embedded JSON manifest, loaded with `allow_pickle=False`. Inference runs in NumPy. scikit-learn moved to the `train` extra. An equivalence test compares against scikit-learn.
- Record the gazetteer schema version, content hash and build metadata. The model manifest records the feature list, training configuration and gazetteer hash. Loading refuses a mismatch, and `tahdeed verify` checks all of it.
- Vendor Leaflet, remove remote fonts, make the tile server configurable (`TAHDEED_TILE_URL`) and add a no basemap mode.
- Add property based fuzzing with Hypothesis for `normalize`, `parse` and `resolve`, checking that they never raise and stay within a time bound.
- Add a per query time budget (default 250 ms) that degrades gracefully and says so.
- Add an audit log with request id, SHA 256 of the query (raw text only with `TAHDEED_LOG_RAW=1`), status, tier, latency and versions.
- Put `degraded`, `calibrated` and the ranker name in every response, and report versions and checksums on `/health`.
- Add the Dockerfile (non root, read only friendly, health check), a pinned constraints file, a CI matrix for Python 3.11 to 3.13, a coverage gate and `pip-audit`.
- Add multi process `tahdeed batch` and `tahdeed bench` (load time, resident memory, p50, p95, p99, queries per second).
- Harden the HTTP layer: security headers including a content security policy, a body size limit, an optional bearer token, request ids, and no stack traces in errors.

Measured effect

- NumPy inference matches scikit-learn to 1e-13.
- Headline dev metrics are unchanged from round 1 (64.5% resolved, 98.2% precision, 67.4% forced top 1).
- Median latency 5.7 ms, p99 16.1 ms, 165 queries per second on one core, 486 MB resident.
- Load time rose from about 7 s to 18.8 s, caused by content hashing, ambiguity tables and sibling key indices. This was recorded and addressed in the final round.
- The dashboard was checked with every host blocked except the tile server.
- The Dockerfile had not been built at this point, because the development environment had no container runtime.

## 5. Development round 3: scientific controls

Problems found

- Every number came from one generator written by the author of the matcher. That generator perturbs the English OSM names, whereas real users produce Latin text from the Arabic name, through romanisation schemes, dialect pronunciation and digits used as letters. That process was not tested.
- There were no ablations for the eight claimed components: skeleton keys, consonant class siblings, fuzzy full name spans, dynamic programming span selection, interpolation, the landmark tier, calibration and hole aware training.
- The baseline was weak, and there was no raw score control for calibration.
- Differences between systems were quoted without a paired test.
- Reproduction was manual, with no environment record in the result files.
- Calibration was reported as a single ECE value with no reliability or risk coverage plots.

Changes

- Write generator v2: Latin text produced from the Arabic names in three styles (formal, Gulf informal, Arabizi with digits), sharing no code or tables with v1 or the matcher.
- Add inference time ablations through a `Flags` object, with paired bootstrap differences.
- Add two baselines: character n gram TF-IDF nearest neighbour over address strings, and the same candidates scored by the raw uncalibrated model.
- Add a single reproduction command, fixed seeds and an environment record in every result file.
- Add figures (reliability, risk coverage, hole sensitivity, generator gap), a model card, a data card and a methodology document.

Measured effect

| Question | Result |
|---|---|
| Does it hold on queries from the independent generator? | Accuracy does not: forced top 1 within 50 m falls from 66.0% (v1) to 49.8% (v2). Calibration does: precision of confident answers moves from 98.1% to 97.0%. Arabizi is the hardest style at 22.7%. |
| Which components help? | The ranker (+27.2 points over hand set confidence), interpolation (+8.5), hole aware training (+4.1 points, ECE 0.050 to 0.012), dynamic programming selection (+1.8), fuzzy full name spans (+0.8). |
| Which do not? | Consonant class matching and sibling keys show no measurable effect (interval spans zero). Removing all three recall aids changes top 1 by −0.4 points, not significant. |
| Is isotonic calibration useful? | No evidence. ECE is 0.007 without it and 0.012 with it. |
| Strong baseline | Character 3 to 4 gram TF-IDF nearest neighbour scores 37.9% against 51.2% for the full system on the mixed benchmark (−13.3 points, CI −15.0 to −11.5). |

Of eight predictions, five hit, one was partial, and two missed or nearly missed. The main conclusion was that the recall machinery added in round 1 does not move the benchmark and that the transliteration problem lay elsewhere: digits used as letters, vowel letters that become consonants, and dialect substitutions.

## 6. Development round 4: Arabic specific matching

Problems found

- Arabizi writes ع as 3, ح as 7, خ as 5, ء as 2, ص as 9, ط as 6 and غ as 8. Words such as "3ali" were read as house numbers and the name never matched. This was the main reason Arabizi sat at 22.7%.
- Romanised street type words (mamar, sikka, shari3, tareeq, dawar) were not recognised, so the type word stayed in the name span and broke the key.
- The article set was incomplete. The Arabic آل (family of) and assimilated Latin forms (el, ell, il, aal) were not all stripped, so "Al Nahyan" and "Aal Nahyan" had different keys. A trailing article could end a span and outcompete the real full name span.
- City aliases were filtered by key length. "Al Ain" has the skeleton `n`, one letter, so the city was dropped from many queries.
- The landmark tier had no benchmark, and no queries were written by a person.
- Contact details inside free text (phone numbers, emails, Emirates ID numbers) would have reached the matcher and the audit log.
- No path existed to an authoritative registry.

Changes

- Decode Arabizi digits inside words of two or more letters, so that "12a" stays a house number.
- Add the romanised street types, extend the article set, and reject spans that end in an article.
- Exempt city alias keys from the minimum length filter.
- Add a landmark query generator and an on and off study.
- Add a hand written set of 40 queries and the `tahdeed gold` command. It is small on purpose and is a smoke test, not a benchmark to quote precision from.
- Add a PII guard (`privacy.py`) that removes phone numbers, emails and Emirates ID numbers before matching.
- Add the `RegistryAdapter` protocol. It is an interface only and is not connected to any registry.

Measured effect

| Question | Before | After |
|---|---|---|
| v2 forced top 1 within 50 m | 49.8% | 61.0% |
| Arabizi | 22.7% | 48.8% |
| Gulf and formal styles | 57.8% and 60.5% | 64.6% and 65.7% |
| v2 precision of resolved answers | 97.0% | 97.6% |
| v1 held out resolved share and precision | 64.5% and 98.2% | 67.2% and 98.5% |
| Landmark queries within 200 m | not measured | 75.3% (0.1% with the tier off) |
| Hand written set within 50 m | not measured | 75.0% (n=40) |

Digit letters and article handling, not consonant class matching, were the transliteration problem. The landmark tier had been shipping without being exercised; the first benchmark showed 0% with and without it, caused by a ranker that had never seen relation queries and a trailing city name that swallowed the landmark span. Both were fixed. Sibling street keys now show a small significant gain (+0.7 points) and isotonic calibration no longer differs from raw scores.

## 7. Development round 5: final checks and the sealed evaluation

Problems found

- Confident wrong answers when a common street name exists in several cities. The hand written set produced two answers more than 100 km away at a probability near 0.7. In one, a coarse key merged a street word with the neighbouring area word. In the other, a span crossed a street type word into the area and city.
- Training and evaluation data are synthetic, and the 40 row set has about 13 points of sampling uncertainty.
- The registry is OpenStreetMap, not an official source. Missing records are the dominant error.
- Landmark evaluation tests finding the landmark, not the offset that "near" implies. The shipped radius table is a judgement.
- Interpolation is the largest single contributor (+9.8 points) and the least verified, since it assumes house numbers increase along a street.
- Load time was 19 s after the round 1 index work.

Changes

- Add an interior street type guard: a span that contains a street type word that is not at its edge is rejected. This fixed one of the two long distance errors.
- Memoise the name to key generation, since the same street names recur across thousands of rows. Load time fell from 19 s to 8 s.
- Retrain both models on the final code and confirm no regression against round 4.
- Run the sealed split once, with predictions written first.
- Regenerate every number in the documents from the result files.
- Keep isotonic calibration, because it is no longer significantly different from raw scores and is harmless, and say so in the model card.

Measured effect

| | Round 4 (dev) | Final (dev) | Final (sealed, earlier model) |
|---|---|---|---|
| Held out resolved share and precision | 67.2% and 98.5% | 69.4% and 98.8% | 65.5% and 98.7% |
| Held out forced top 1 within 50 m | 70.1% | 72.7% | 68.3% |
| v2 generator forced top 1 | 61.0% | 64.4% | 66.0% |
| Arabizi (v2) | 48.8% | 51.3% | 53.7% |
| Landmark within 200 m | 75.3% | 74.2% | 75.8% |
| Hand written set within 50 m (n=40, partly tuned on) | 75.0% | 85.0% | not run |
| Load time | about 19 s | 8 s | 8 s |

The guard was a net gain everywhere except a one point dip on landmark queries. Of seven sealed predictions, four hit, one was half correct, one was a near miss and two missed: the top 1 gap between dev and sealed (F1), and calibration on the POI benchmark (ECE 0.054, F4). The sealed split holds 10% of districts, so some spread between splits is expected. The POI result reflects weaker truth for that benchmark.

## 8. Open items

- Cross token coarse merge. A coarse key can merge a street word with an area word and answer confidently in the wrong city. It needs a feature for a span that swallowed a token matching an area exactly, which means another retraining cycle with its own evaluation.
- Real query logs. No query in any benchmark came from a real user. Only real logs close this gap.
- An official registry adapter. `RegistryAdapter` is an interface only.
- Learned Arabic to Latin matching. Deferred, because the only labelled pairs are the paired names in the gazetteer and the rule keys cover the known failures.
- Landmark offsets. The benchmark tests finding the landmark, and the radius table for relation phrases has no measured basis.
- Interpolation has no external check against surveyed addresses.
- The Docker image had not been built in the development environment. The continuous integration workflow builds it.
