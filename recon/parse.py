"""Tolerant parsers for the amounts and dates found in Indian bank and gateway exports."""

from __future__ import annotations

import math
import re
from datetime import date, datetime

_EMPTY = {"", "nan", "none", "null", "-", "--", "na", "n/a"}


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip().lower() in _EMPTY


def parse_amount(value) -> float | None:
    """Parse '1,23,456.00', '₹ 499', '(250.00)', '500.00 Cr', '-12.5' and friends."""
    if is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    for token in ("₹", "INR", "Rs.", "Rs"):
        text = text.replace(token, "")
    text = text.replace(",", "").replace(" ", "")
    suffix = re.search(r"(cr|dr)\.?$", text, re.IGNORECASE)
    if suffix:
        negative = negative or suffix.group(1).lower() == "dr"
        text = text[: suffix.start()]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    elif text.startswith("+"):
        text = text[1:]
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


# Day-first formats come before month-first ones: Indian statements are day-first,
# so an ambiguous column (every day <= 12) resolves the Indian way.
DATE_FORMATS = [
    "%d/%m/%y", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%d-%B-%Y", "%d %B %Y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%m/%d/%Y", "%m/%d/%y",
]


def _date_part(text: str) -> str:
    # Drop a trailing time ("04/09/2026 11:22:10", "2026-09-04T11:22:10").
    return re.split(r"[ T]", text.strip(), maxsplit=1)[0]


def detect_date_format(values) -> str | None:
    """Pick the single format that parses the most values in a column."""
    samples = [_date_part(str(v)) for v in values if not is_blank(v) and not isinstance(v, (date, datetime))]
    if not samples:
        return None
    best, best_hits = None, 0
    for fmt in DATE_FORMATS:
        hits = 0
        for s in samples:
            try:
                datetime.strptime(s, fmt)
                hits += 1
            except ValueError:
                pass
        if hits > best_hits:
            best, best_hits = fmt, hits
    return best


def parse_dates(values) -> list[date | None]:
    values = list(values)
    fmt = detect_date_format(values)
    out: list[date | None] = []
    for v in values:
        if isinstance(v, datetime):
            out.append(v.date())
        elif isinstance(v, date):
            out.append(v)
        elif is_blank(v) or fmt is None:
            out.append(None)
        else:
            try:
                out.append(datetime.strptime(_date_part(str(v)), fmt).date())
            except ValueError:
                out.append(None)
    return out


def norm_text(value) -> str:
    return "" if is_blank(value) else str(value).strip()


def squash(text: str) -> str:
    """Uppercase and drop everything but letters and digits, for substring matching of UTRs."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


_UTR_TOKEN = re.compile(r"[A-Z0-9]{12,22}")


def extract_utr_candidates(text: str) -> list[str]:
    """Tokens that look like NEFT/RTGS/IMPS references: 12-22 chars, letters and >= 6 digits.

    Filters out IFSC codes (11 chars) and the pure-digit references UPI uses.
    """
    tokens = _UTR_TOKEN.findall(text.upper())
    return [t for t in tokens if sum(c.isdigit() for c in t) >= 6 and any(c.isalpha() for c in t)]


def inr(amount: float) -> str:
    """Format a number the Indian way: 1,23,456.50"""
    negative = amount < 0
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if negative else ''}{whole}.{frac}"
