# Review 4: ATRC (Arabic-language and Gulf-context AI)

*Reviewer stance: someone who works on Arabic NLP and knows how Emiratis actually write addresses.
Round 3 showed that the machinery built for transliteration variants does not move the benchmark.
The question for this round is why, and what real Arabic-script and Gulf phenomena are missing.*

## Critique

**A1. Digits as letters are treated as numbers.** Arabizi writes ع as 3, ح as 7, خ as 5, ء as 2,
ص as 9, ط as 6, غ as 8. "3ali" became a house-number-like token and the name never matched.
This is the main reason Arabizi sits at 22.7%.

**A2. Romanised street-type words are not recognised.** "Mamar", "sikka", "shari3", "tareeq",
"dawar" are written all the time but only the Arabic forms were in the type table, so the type
word stayed inside the name span and broke the key.

**A3. Articles.** آل (family of, "Aal Nahyan") and the assimilated Latin articles
(el, ell, il, aal, ...) were not all stripped, so "Al Nahyan" and "Aal Nahyan" had different keys.
A trailing article ("... Al") could end a span and outcompete the real full-name span.

**A4. City aliases were filtered by length.** "Al Ain" has skeleton "n": one letter, discarded,
so the city was dropped from many queries.

**A5. Landmark queries have no benchmark.** Residents describe places relative to landmarks
("behind Lulu, Al Nahda"). The landmark tier exists but nothing measures it.

**A6. Both benchmarks are machine-written.** Even the independent v2 generator is code. There is
no set of queries written the way a person writes them.

**A7. Contact details inside free text** (phones, emails, Emirates ID) would reach the matcher
and the audit log.

**A8. No path to an authoritative registry.** The hole study says missing records are the
dominant error, and only an official registry fixes that. There is no interface for one.

## Checklist (✅ done this round)

- [x] **A1** Decode Arabizi digits inside words (2+ letters, so "12a" stays a house number).
- [x] **A2** Romanised street-type words: mamar/momar, sikka, shari/shari3/share3, tareeq, dawar, jisr, midan.
- [x] **A3** Article set extended (aal, ael, ell, il, ul); reject spans ending in an article.
- [x] **A4** City-alias keys exempt from the minimum-length filter ("Al Ain" now resolves).
- [x] **A5** Landmark query generator (`make_landmark_queries`) and an on/off study.
- [x] **A6** Hand-written gold set (40 queries) and `tahdeed gold`. Small on purpose: a smoke test, not a benchmark to quote precision from.
- [x] **A7** PII guard (`privacy.py`): phone, email, Emirates ID removed before matching; noted in the result.
- [x] **A8** `RegistryAdapter` protocol. Interface only; not wired in, no official adapter.
- [ ] Learned Arabic↔Latin matching (T7). Deferred: no labelled transliteration pairs beyond what the gazetteer's own paired names give, and the rule keys now cover the known failures.

## Result of this round (`docs/studies.json`, `docs/gold.json`, `docs/PREDICTIONS.md`)

| Question | Before (Round 3) | After |
|---|---|---|
| v2 (from-Arabic) forced top-1 ≤50 m | 49.8% | **61.0%** |
| Arabizi | 22.7% | **48.8%** |
| Gulf / formal | 57.8% / 60.5% | 64.6% / 65.7% |
| v2 precision of resolved answers | 97.0% | 97.6% |
| v1 held-out: resolved share / precision | 64.5% / 98.2% | 67.2% / 98.5% |
| Landmark queries, within 200 m | not measured | 75.3% (0.1% with the tier off) |
| Hand-written gold set, ≤50 m | not measured | 75.0% (n=40) |

Side effects worth reading: with the new matching, sibling street keys now show a small
significant gain (+0.7 points) and the isotonic step no longer differs from raw scores
(−0.02, not significant). The finding that mattered: digit letters and article handling, not
consonant-class matching, were the transliteration problem. The landmark tier had been
shipping without ever being exercised; a benchmark for it exposed that within minutes.

Honest limits that remain: the gold set shows confident errors when a common street name
exists in several cities and the query omits the city (two answers >100 km off at
p≈0.65–0.75). The gold set has 40 rows, so its 75% has roughly ±13 points of sampling
uncertainty. The landmark benchmark's truth is the landmark itself.
