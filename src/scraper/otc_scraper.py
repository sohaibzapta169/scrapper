from __future__ import annotations

import json
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

from src.models import ListingRecord
from src.scraper.utils import collect_dates_from_text, date_in_range, normalize_ticker


class OtcMarketsScraper:
    BASE_URL = "https://www.otcmarkets.com/stock/{ticker}/overview"
    KEYWORDS = (
        "grace period",
        "grace",
        "caveat emptor",
        "limited information",
        "current information",
        "expert market",
        "otcqx",
        "otcqb",
        "pink",
        "warning",
        "otc markets",
        "market tier",
    )

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                )
            }
        )

    def fetch_ticker(
        self,
        ticker: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[ListingRecord]:
        ticker = normalize_ticker(ticker)
        url = self.BASE_URL.format(ticker=ticker)
        try:
            resp = self.session.get(url, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        status_lines = self._extract_status_lines(soup)
        status_lines.extend(self._extract_from_next_data(soup))
        status_lines = list(dict.fromkeys(line.strip() for line in status_lines if line.strip()))

        if not status_lines:
            return []

        records: list[ListingRecord] = []
        for line in status_lines:
            parsed_date = None
            found_dates = collect_dates_from_text(line)
            if found_dates:
                parsed_date = found_dates[0]
            if not date_in_range(parsed_date, start_date, end_date):
                continue

            records.append(
                ListingRecord(
                    ticker=ticker,
                    source="OTC",
                    status=self._classify_status(line),
                    description=line[:400],
                    relevant_date=parsed_date,
                    raw_excerpt=line[:800],
                )
            )

        unique: dict[str, ListingRecord] = {}
        for record in records:
            unique[record.signature()] = record
        return list(unique.values())

    def _extract_status_lines(self, soup: BeautifulSoup) -> list[str]:
        lines: list[str] = []
        text_candidates = []
        for node in soup.select("div,span,p,li,h1,h2,h3,h4,h5"):
            text = node.get_text(" ", strip=True)
            if text:
                text_candidates.append(text)

        for text in text_candidates:
            low = text.lower()
            if any(keyword in low for keyword in self.KEYWORDS):
                lines.append(text)
        return lines

    def _extract_from_next_data(self, soup: BeautifulSoup) -> list[str]:
        lines: list[str] = []
        script = soup.select_one("script#__NEXT_DATA__")
        if not script or not script.string:
            return lines
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError:
            return lines

        collected = self._collect_status_like_fields(payload)
        lines.extend(collected)
        return lines

    def _collect_status_like_fields(self, data: object, parent_key: str = "") -> list[str]:
        output: list[str] = []
        status_like = ("status", "grace", "tier", "market", "caveat", "warning", "info")
        if isinstance(data, dict):
            for key, value in data.items():
                key_low = str(key).lower()
                full_key = f"{parent_key}.{key_low}" if parent_key else key_low
                if isinstance(value, (str, int, float)):
                    text = str(value).strip()
                    if text and any(tag in key_low for tag in status_like):
                        output.append(f"{full_key}: {text}")
                    elif text and any(keyword in text.lower() for keyword in self.KEYWORDS):
                        output.append(text)
                else:
                    output.extend(self._collect_status_like_fields(value, full_key))
        elif isinstance(data, list):
            for item in data:
                output.extend(self._collect_status_like_fields(item, parent_key))
        return output

    def _classify_status(self, text: str) -> str:
        low = text.lower()
        if "grace" in low:
            return "Grace Period"
        if "caveat" in low or "warning" in low:
            return "Warning"
        if "expert market" in low:
            return "Expert Market"
        if "otcqx" in low:
            return "OTCQX"
        if "otcqb" in low:
            return "OTCQB"
        if "pink" in low:
            return "Pink"
        if re.search(r"\b(current|limited)\s+information\b", low):
            return "Information Tier"
        return "Status Match"
