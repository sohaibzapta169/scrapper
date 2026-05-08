from __future__ import annotations

import csv
import io
from datetime import date

import cloudscraper

from src.models import ListingRecord
from src.scraper.utils import collect_dates_from_text, date_in_range, normalize_ticker, try_parse_date


class FinraScraper:
    API_URL = "https://api.finra.org/data/group/otcMarket/name/otcDailyList"

    SYMBOL_FIELDS = (
        "newsymbolcode",
        "oldsymbolcode",
        "symbolcode",
        "symbol",
        "issuesymbol",
    )

    DATE_FIELDS = (
        "effectivedate",
        "dailylistdate",
        "date",
        "recorddate",
        "exdate",
        "payabledate",
    )

    # Maps raw FINRA reason/type codes to our normalized event type categories
    EVENT_TYPE_KEYWORDS = {
        "Additions": ("add", "new", "list"),
        "Deletions": ("delete", "delist", "remove"),
        "Symbol/Name Changes": ("symbol", "name", "change", "rename"),
        "Financial Status Indicator Change": ("financial status", "fsi", "indicator"),
        "OATS Reportable Flag Change": ("oats", "reportable"),
        "Regulatory Transaction Fee Flag Change": ("regulatory", "fee", "transaction fee"),
        "Unit of Trades Change": ("unit", "trade", "lot"),
        "Market Category Change": ("market category", "category change", "tier"),
        "Bankruptcy": ("bankrupt",),
        "Dividends / Distributions / Splits": ("dividend", "distribution", "split", "spinoff"),
    }

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.scraper = cloudscraper.create_scraper()

    def fetch_ticker(
        self,
        ticker: str,
        start_date: date | None,
        end_date: date | None,
        event_types: list[str] | None = None,
    ) -> list[ListingRecord]:
        ticker = normalize_ticker(ticker)
        records: list[ListingRecord] = []

        try:
            resp = self.scraper.get(self.API_URL, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except Exception:
            return records

        text = resp.text
        if ticker not in text.upper():
            return records

        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            symbol = self._extract_symbol(row)
            if symbol != ticker:
                continue

            record = self._record_from_row(row, ticker)

            # Filter by event type if specified
            if event_types and record.event_type:
                if record.event_type not in event_types:
                    continue

            if date_in_range(record.relevant_date, start_date, end_date):
                records.append(record)

        unique: dict[str, ListingRecord] = {}
        for record in records:
            unique[record.signature()] = record
        return list(unique.values())

    def _extract_symbol(self, row: dict[str, str | None]) -> str:
        for key, value in row.items():
            if key is None:
                continue
            key_low = key.lower().replace(" ", "")
            if key_low in self.SYMBOL_FIELDS:
                raw = value or ""
                if isinstance(raw, str) and raw.strip():
                    return normalize_ticker(raw)
        return ""

    def _record_from_row(self, row: dict[str, str | None], ticker: str) -> ListingRecord:
        def safe_str(v: object) -> str:
            if v is None:
                return ""
            if isinstance(v, str):
                return v.strip()
            if isinstance(v, (list, tuple)):
                return " ".join(str(x) for x in v).strip()
            return str(v).strip()

        normalized = {str(k).strip().lower().replace(" ", ""): safe_str(v) for k, v in row.items()}

        reason = (
            normalized.get("dailylistreasoncode")
            or normalized.get("dailylistreasondescription")
            or normalized.get("reasoncode")
            or normalized.get("action")
            or normalized.get("dailylisttype")
            or "Daily List Entry"
        )

        description = (
            normalized.get("newsecuritydescription")
            or normalized.get("oldsecuritydescription")
            or normalized.get("securitydescription")
            or normalized.get("issuename")
            or normalized.get("companyname")
            or reason
        )

        status = self._classify_status(reason, normalized)
        event_type = self._classify_event_type(reason, normalized)

        relevant_date = None
        for field in self.DATE_FIELDS:
            value = normalized.get(field, "")
            if value:
                parsed = try_parse_date(value)
                if parsed:
                    relevant_date = parsed
                    break

        if relevant_date is None:
            all_values = " ".join(normalized.values())
            found_dates = collect_dates_from_text(all_values)
            if found_dates:
                relevant_date = found_dates[0]

        non_empty = {k: v for k, v in normalized.items() if v}
        excerpt = " | ".join(f"{k}: {v}" for k, v in list(non_empty.items())[:15])

        return ListingRecord(
            ticker=ticker,
            source="FINRA",
            status=status,
            description=f"{description} - {reason}"[:400],
            relevant_date=relevant_date,
            raw_excerpt=excerpt[:800],
            event_type=event_type,
        )

    def _classify_event_type(self, reason: str, row: dict[str, str]) -> str:
        """Classify the FINRA record into one of the standard event types."""
        combined = f"{reason} {' '.join(row.values())}".lower()

        for event_type, keywords in self.EVENT_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in combined:
                    return event_type

        # Check bankruptcy flag explicitly
        if row.get("bankruptcyflag", "").upper() == "Y":
            return "Bankruptcy"

        return "Other"

    def _classify_status(self, reason: str, row: dict[str, str]) -> str:
        low = reason.lower()

        if "add" in low or "new" in low:
            return "Addition"
        if "delete" in low or "remove" in low:
            return "Deletion"
        if "symbol" in low and "change" in low:
            return "Symbol Change"
        if "name" in low and "change" in low:
            return "Name Change"
        if "dividend" in low:
            return "Dividend"
        if "split" in low:
            return "Stock Split"
        if "merger" in low or "acquisition" in low:
            return "Merger/Acquisition"
        if "suspension" in low or "halt" in low:
            return "Trading Suspension"
        if "deficient" in low or "delinquent" in low:
            return "Deficient"

        bankruptcy = row.get("bankruptcyflag", "").upper()
        if bankruptcy == "Y":
            return "Bankruptcy"

        return "Daily List Entry"
