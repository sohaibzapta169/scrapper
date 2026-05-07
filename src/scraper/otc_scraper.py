from __future__ import annotations

import re
from datetime import date

import cloudscraper
from bs4 import BeautifulSoup

from src.models import ListingRecord
from src.scraper.utils import collect_dates_from_text, date_in_range, normalize_ticker


class OtcMarketsScraper:
    BASE_URL = "https://www.otcmarkets.com/stock/{ticker}/overview"

    STATUS_KEYWORDS = (
        "grace period",
        "caveat emptor",
        "expert market",
        "shell risk",
        "bankruptcy",
        "delinquent",
        "dark",
        "grey market",
        "stop sign",
        "yield sign",
        "skull",
    )

    TIER_KEYWORDS = (
        "pink limited",
        "pink current",
        "pink no information",
        "otcqx",
        "otcqb",
        "pink",
        "expert",
        "grey",
    )

    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds
        self.scraper = cloudscraper.create_scraper()

    def fetch_ticker(
        self,
        ticker: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[ListingRecord]:
        ticker = normalize_ticker(ticker)
        url = self.BASE_URL.format(ticker=ticker)

        try:
            resp = self.scraper.get(url, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except Exception:
            return []

        html = resp.text
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        records: list[ListingRecord] = []

        # Check page title for ticker presence
        title = soup.select_one("title")
        title_text = title.get_text(" ", strip=True) if title else ""

        # Extract any status/tier info from the page
        page_text = soup.get_text(" ", strip=True).lower()

        # Detect market tier from page content
        tier_found = None
        for kw in self.TIER_KEYWORDS:
            if kw in page_text:
                tier_found = self._classify_tier(kw)
                break

        if tier_found:
            records.append(
                ListingRecord(
                    ticker=ticker,
                    source="OTC",
                    status=tier_found,
                    description=f"{ticker} - OTC Markets - {tier_found}",
                    relevant_date=None,
                    raw_excerpt=title_text[:800],
                )
            )

        # Look for warning/status keywords
        for kw in self.STATUS_KEYWORDS:
            if kw in page_text:
                status = self._classify_status(kw)
                # Find context around the keyword
                idx = page_text.find(kw)
                context = page_text[max(0, idx - 50) : idx + 100]
                dates = collect_dates_from_text(context)

                records.append(
                    ListingRecord(
                        ticker=ticker,
                        source="OTC",
                        status=status,
                        description=f"{ticker} - {status} detected",
                        relevant_date=dates[0] if dates else None,
                        raw_excerpt=context[:800],
                    )
                )
                break

        # Look for grace period with dates
        grace_pattern = re.compile(
            r"grace\s+period[^.]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})",
            re.I,
        )
        matches = grace_pattern.findall(html)
        for match in matches[:2]:
            dates = collect_dates_from_text(match)
            if dates and date_in_range(dates[0], start_date, end_date):
                records.append(
                    ListingRecord(
                        ticker=ticker,
                        source="OTC",
                        status="Grace Period",
                        description=f"Grace period deadline: {match}",
                        relevant_date=dates[0],
                        raw_excerpt=match,
                    )
                )

        # Filter by date range and deduplicate
        unique: dict[str, ListingRecord] = {}
        for record in records:
            if record.relevant_date is None or date_in_range(record.relevant_date, start_date, end_date):
                unique[record.signature()] = record

        return list(unique.values())

    def _classify_tier(self, text: str) -> str:
        low = text.lower()
        if "otcqx" in low:
            return "OTCQX"
        if "otcqb" in low:
            return "OTCQB"
        if "pink limited" in low:
            return "Pink Limited"
        if "pink current" in low:
            return "Pink Current"
        if "pink no information" in low:
            return "Pink No Information"
        if "expert" in low:
            return "Expert Market"
        if "grey" in low or "gray" in low:
            return "Grey Market"
        if "pink" in low:
            return "Pink"
        return "OTC"

    def _classify_status(self, text: str) -> str:
        low = text.lower()
        if "grace" in low:
            return "Grace Period"
        if "caveat" in low or "skull" in low:
            return "Caveat Emptor"
        if "stop" in low:
            return "Stop Sign"
        if "yield" in low:
            return "Yield Sign"
        if "shell" in low:
            return "Shell Risk"
        if "bankruptcy" in low:
            return "Bankruptcy"
        if "delinquent" in low:
            return "Delinquent"
        if "dark" in low:
            return "Dark/Defunct"
        return "Warning"
