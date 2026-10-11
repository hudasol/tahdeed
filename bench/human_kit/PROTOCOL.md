# Organiser protocol

This protocol is for the person collecting the human-written benchmark. The kit contains **no data**: every description in the final dataset must come from a real volunteer. Never write, paraphrase, "augment" or generate descriptions yourself, and never fill gaps with model output.

> Not legal advice. Before recruiting, review `CONSENT.md` / `CONSENT.ar.md`, fill the `<...>` placeholders, and obtain ethics approval if your institution requires it.

## 1. Targets

| Item | Target |
|---|---|
| Volunteers | 25 to 40 (aim 30+) |
| Places per volunteer | 5 (public places only) |
| Descriptions | about 125 to 200 in total, after dropping skips and duplicates |
| Coverage per place | roughly equal (`assign.py` keeps every place covered and the spread small; with 60 places and 35 volunteers each place gets about 2 to 4 descriptions) |

With so few descriptions per place, the benchmark estimates how the resolver does on **people**, not on any single place; report intervals (the evaluation does).

## 2. Recruiting a spread of people

Recruit adults (18+) who actually use taxis, delivery apps or ride-hailing in the UAE. Track the mix **on your own private sheet, not in the dataset**, and fill the quotas below as far as you can. Do not ask for, or record, names next to codes.

- **Emirate of residence:** Dubai 8 to 10, Abu Dhabi 6 to 8, Sharjah 4 to 5, and at least 2 each from Ajman / Al Ain / Ras Al Khaimah / Fujairah / Umm Al Quwain if possible. Residents often only know their own emirate well, so a spread is what keeps the assigned places from being unfamiliar.
- **Nationality and background:** Emirati, other Arab, South Asian, Southeast Asian, Western and African residents. Different groups give directions in very different ways.
- **Age:** roughly even across 18 to 29, 30 to 44, 45 to 64, and a few 65+.
- **Writing habit:** include people who normally write Arabic script, English, **Arabizi**, and a mix. Ask a screening question in person ("how do you usually text a driver?") and keep the answer private. Aim for at least 6 to 8 volunteers in each of the Arabic, English and Arabizi/mixed groups so that each script has a usable number of descriptions.
- **Channels:** several unrelated ones (university groups, workplaces, community centres, family and friends of friends). Avoid recruiting only from your own circle or only from people who know the project.

Do not pay per answer or reward "good" answers. A small thank-you gift for everybody is fine. Do not pressure anyone.

## 3. Preparing the sheets

1. Check `places.csv` (read `places_sources.md` for how each coordinate was obtained). Use only `A`/`B` places. Remove any place you think is sensitive or that volunteers could not reasonably be expected to know.
2. Create a `codes.txt` (one code per line) with `assign.py --n 35 --out private/sheets` (random codes are generated) **or** your own list. Never reorder or insert in the middle after sheets are issued; append instead.
3. Run `python bench/human_kit/assign.py --codes private/sheets/codes.txt --out private/sheets --form bench/human_kit/form/index.html`. This writes, per code, a personalised offline form `form_<code>.html` that embeds only that volunteer's five places (**name and category only, no coordinates**), plus `assignment_key.csv` for you.
4. Keep `private/` out of git.

## 4. Avoiding priming (important)

The benchmark measures how people speak, not how well they read an address. Therefore:

- Show **only the place name (English and Arabic) and its category**. Never the address, the street, the neighbourhood name you found, or the coordinates.
- **No map**, no photo, no link, no "hint". Ask volunteers not to look anything up; if they do not know a place they tick *I don't know this place*.
- **Order is randomised** per volunteer (the assignment shuffles the five places deterministically); do not reorder them.
- Do not show example descriptions of real listed places. The two examples in `INSTRUCTIONS*.md` use invented places on purpose.
- Do not tell volunteers what the software is, what it is good or bad at, or what "a good answer" looks like. Do not say "be precise" or "include the street".
- Do not explain, correct or edit any text, and never ask a volunteer to redo an answer because it is vague. Vague answers are data.
- Give instructions in the volunteer's preferred language (EN or AR form), but do not suggest which script to write in.
- Do the task independently: volunteers should not compare answers with each other.

## 5. Running the collection

- Send the volunteer their personal `form_<code>.html` together with `INSTRUCTIONS.md` or `INSTRUCTIONS.ar.md` and the consent text (the form also shows a consent summary).
- The volunteer opens it in a browser, completes it offline, clicks **Download my responses**, and sends you the `tahdeed_responses_<code>.json` file (email attachment, messaging app, or USB stick).
- Volunteers who cannot use the form may dictate to you; type exactly what they say into `form/responses_template.csv` (one row per place, `consent_agreed` = `yes` only if they said so). Do not paraphrase.
- Chase gently once. Do not fill missing answers.

## 6. Storing and submitting the data

1. Save received files in an **encrypted, access-restricted folder** (never in the repo). Do not rename them in a way that adds a person's name.
2. Do not store a table of "code, person". If you must (to send reminders), keep it in a separate place and **destroy it when collection closes**.
3. Ingest (see `README.md`): `python -m tahdeed.human ingest private/responses/*.json --out private/human.jsonl --salt-file private/salt.txt`. Keep `salt.txt` private; it is what makes the hashed volunteer ids unlinkable to codes.
4. Open `private/human.jsonl` and review every record whose `flags` contain `review:...`. Delete the line if it looks like a personal address or identifies anyone; otherwise remove the `review:` flag. Read through the rest quickly for personal information that automatic checks cannot catch (names of people, employers, car plates).
5. Delete the raw response files once the dataset is checked and the withdrawal period in the consent has ended. Honour withdrawal requests (match the volunteer's code to the file *before* ingest).
6. **Publication:** publish `human.jsonl`, `places.csv` and `places_sources.md` under the licence stated in the consent (CC BY-SA 4.0 by default). Do not publish the salt, codes, raw files, the assignment key, or any recruitment sheet. Credit OpenStreetMap contributors (ODbL) and Wikidata (CC0) for the place coordinates.

## 7. Using the results honestly

- This set is **for evaluation only**. Do not tune the resolver on it. If you want to improve the model using these texts, split them first (by volunteer) and report only on the held-out part.
- Decide the metrics before you look: within 50 m / 200 m / 1 km, status mix, and resolved-only precision, by script, with 95% intervals. Report N descriptions and N volunteers every time.
- With fewer than 20 descriptions `evaluate` prints `pending real data` and no numbers; do not report anything from a handful of answers.
- Report limitations: a volunteer text describes how to *reach* a public place and often contains no formal address; the resolver gets the place name plus the text; the truth point of a large site (mall, campus, park) is a centroid, so exact-position rates are conservative; and descriptions are clustered by volunteer and place, so intervals are optimistic.
