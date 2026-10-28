# Draft: request for a data licence for Makani (not sent)

Status: **draft for Huda Mueen to review and send herself.** Nothing has been sent. Fill the bracketed
fields before sending. Suggested channel: the Dubai Municipality GIS Centre, through the contact
form or email address listed on <https://www.dm.gov.ae/open-data/open-data-for-makani/> (verify the
current address before sending).

---

**To:** GIS Centre, Dubai Municipality
**From:** Huda Mueen, [contact email], [telephone]
**Date:** [date of sending]
**Subject:** Request for a written licence to use Makani building entrance data in an open research address resolver

Dear Sir or Madam,

I am writing to request a written licence, or guidance on the correct procedure, for using Makani
data in a research project on address resolution for the United Arab Emirates.

**The project.** Tahdeed (<https://github.com/hudasol/tahdeed>) is an open source system that reads
an address written in free text, in Arabic, English or a mixture of both, and returns a location
together with a calibrated statement of how likely that location is to be correct. When the text
is insufficient, it declines to answer and asks for the missing detail (for example the building
number or the city), rather than guessing. It runs offline and does not use any commercial
geocoding service.

**Why Makani matters.** The system currently relies on OpenStreetMap, which is rich in structured
addresses for Abu Dhabi but sparse for Dubai. Our published evaluation therefore reports Dubai
results only for named places, and states plainly that Dubai street addresses cannot yet be
evaluated. Makani is the authoritative reference for building entrances in Dubai. With it, the
system could (a) recognise a Makani number written in an address and return the correct entrance,
and (b) measure its own accuracy in Dubai against an official reference instead of volunteered map
data.

**What we would like to do, subject to your approval.**

1. Use Makani entrance coordinates and numbers as **ground truth for evaluation** (measuring how
   often the system's answer lies within 50 metres of the correct entrance), and publish only
   aggregate accuracy figures.
2. If permitted, use Makani as a **lookup service**: when a user supplies a Makani number, return
   the corresponding entrance. We would comply with any rate limits and access conditions.
3. We would **not** sell Makani data, alter it, or present it as anything other than Dubai
   Municipality's data, and we would credit "Dubai Municipality" wherever results that rely on it
   are shown, as your published terms require.

**A point we would like your guidance on.** Our current address database is derived from
OpenStreetMap and is published under the Open Database Licence, which requires that the combined
database may be redistributed and modified by anyone. We understand that Makani's terms do not
allow this. Unless you advise otherwise, we would therefore keep Makani data **separate** from the
openly licensed database: used only for evaluation and live lookup, never merged into or
redistributed with it.

**Our questions.**

1. May Makani data be used for the purposes in items 1 and 2 above, and under what written terms?
2. Is there a bulk file or an application programming interface for research use, and what are its
   access conditions and rate limits?
3. Is there an Acceptable Usage Policy document that we should read and accept? The open data page
   refers to one but we could not locate it.
4. Is a separate agreement needed for a non commercial research demonstration that is publicly
   accessible?

I would be glad to provide further details about the project, the data handling and the security
measures in place, or to meet at your convenience.

Thank you for your time and consideration.

Yours faithfully,

Huda Mueen
[contact email] · [telephone]
<https://github.com/hudasol/tahdeed>
