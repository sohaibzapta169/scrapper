from __future__ import annotations

import re
from datetime import date

from dateutil import parser as date_parser


def normalize_ticker(value: str) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", value.upper().strip())


def try_parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return date_parser.parse(value, fuzzy=True).date()
    except (ValueError, TypeError, OverflowError):
        return None


def collect_dates_from_text(text: str) -> list[date]:
    if not text:
        return []
    candidates = re.findall(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    out: list[date] = []
    for candidate in candidates:
        parsed = try_parse_date(candidate)
        if parsed:
            out.append(parsed)
    return out


def date_in_range(value: date | None, start_date: date | None, end_date: date | None) -> bool:
    if value is None:
        return True
    if start_date and value < start_date:
        return False
    if end_date and value > end_date:
        return False
    return True
