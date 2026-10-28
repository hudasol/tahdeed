"""PII guard: contact details never help locate an address, so they are removed up front.

Applied at the top of resolution, so they cannot reach matching, notes or the audit log.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# UAE mobiles/landlines: +971 5x xxx xxxx, 00971..., 05x xxx xxxx, 04 xxx xxxx (keeps 10-digit Makani)
_PHONE = re.compile(
    r"(?<!\d)(?:\+|00)971[\s().-]*0?[\s().-]*\d(?:[\s().-]?\d){7,8}(?!\d)"
    r"|(?<!\d)0(?:5\d|[2-47-9])[\s().-]?\d{3}[\s().-]?\d{4}(?!\d)"
)
_EID = re.compile(r"(?<!\d)784[\s-]?\d{4}[\s-]?\d{7}[\s-]?\d(?!\d)")  # Emirates ID


# Arabic-Indic and Eastern Arabic-Indic digits map one to one onto ASCII, so spans found in the
# mapped copy line up with the original and the original characters are what gets removed.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def redact_pii(text: str) -> tuple[str, list[str]]:
    kinds: list[str] = []
    for name, rx in (("email", _EMAIL), ("emirates_id", _EID), ("phone", _PHONE)):
        spans = [m.span() for m in rx.finditer(text.translate(_DIGITS))]
        if not spans:
            continue
        kinds.append(name)
        for a, b in reversed(spans):
            text = text[:a] + " " + text[b:]
    return text, kinds
