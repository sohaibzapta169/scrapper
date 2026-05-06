from __future__ import annotations

import csv
import io
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.models import ListingRecord
from src.scraper.utils import collect_dates_from_text, date_in_range, normalize_ticker, try_parse_date


class FinraScraper:
    DAILY_LIST_URL = "https://otce.finra.org/otce/dailyList"

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
        records: list[ListingRecord] = []

        try:
            resp = self.session.get(self.DAILY_LIST_URL, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException:
            return records

        html = resp.text
        records.extend(self._parse_html_tables(html, ticker, start_date, end_date))

        for file_url in self._extract_file_urls(html):
            records.extend(self._parse_download_file(file_url, ticker, start_date, end_date))

        # Deduplicate by complete record signature.
        unique: dict[str, ListingRecord] = {}
        for record in records:
            unique[record.signature()] = record
        return list(unique.values())

    def _extract_file_urls(self, html: str) -> set[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: set[str] = set()

        for link in soup.select("a[href]"):
            href = link.get("href", "").strip()
            if not href:
                continue
            if re.search(r"\.(csv|txt|xlsx?)($|\?)", href, flags=re.IGNORECASE):
                urls.add(urljoin(self.DAILY_LIST_URL, href))

        # Fall back to a generic regex strategy for dynamic layouts.
        for match in re.findall(r"https?://[^\s\"']+\.(?:csv|txt|xlsx?)", html, flags=re.IGNORECASE):
            urls.add(match)

        return urls

    def _parse_download_file(
        self,
        file_url: str,
        ticker: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[ListingRecord]:
        if not re.search(r"\.(csv|txt)($|\?)", file_url, flags=re.IGNORECASE):
            return []
        try:
            file_resp = self.session.get(file_url, timeout=self.timeout_seconds)
            file_resp.raise_for_status()
        except requests.RequestException:
            return []

        text = file_resp.text
        sample = text[:2048]
        if ticker not in sample.upper() and ticker not in text.upper():
            return []

        out: list[ListingRecord] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            symbol = self._extract_symbol(row)
            if symbol != ticker:
                continue
            record = self._record_from_row(row, ticker)
            if date_in_range(record.relevant_date, start_date, end_date):
                out.append(record)
        return out

    def _extract_symbol(self, row: dict[str, str | None]) -> str:
        symbol_fields = (
            "symbol",
            "ticker",
            "issue symbol",
            "security symbol",
            "otc symbol",
        )
        normalized_row = {str(k).strip().lower(): (v or "") for k, v in row.items()}
        for field in symbol_fields:
            raw = normalized_row.get(field, "")
            if raw.strip():
                return normalize_ticker(raw)
        return ""

    def _record_from_row(self, row: dict[str, str | None], ticker: str) -> ListingRecord:
        normalized = {str(k).strip().lower(): (v or "").strip() for k, v in row.items()}
        status = (
            normalized.get("action")
            or normalized.get("daily list type")
            or normalized.get("event")
            or "Listed"
        )
        description = (
            normalized.get("description")
            or normalized.get("issue name")
            or normalized.get("security description")
            or status
        )
        relevant_date = None
        for key, value in normalized.items():
            if "date" in key:
                maybe = try_parse_date(value)
                if maybe:
                    relevant_date = maybe
                    break
        if relevant_date is None:
            found = collect_dates_from_text(" ".join(normalized.values()))
            relevant_date = found[0] if found else None

        excerpt = " | ".join(f"{k}: {v}" for k, v in normalized.items() if v)
        return ListingRecord(
            ticker=ticker,
            source="FINRA",
            status=status,
            description=description,
            relevant_date=relevant_date,
            raw_excerpt=excerpt[:800],
        )

    def _parse_html_tables(
        self,
        html: str,
        ticker: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[ListingRecord]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[ListingRecord] = []
        for table in soup.select("table"):
            headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
            for row in table.select("tbody tr"):
                cells = [td.get_text(" ", strip=True) for td in row.select("td")]
                if not cells:
                    continue
                combined = " | ".join(cells)
                if ticker not in normalize_ticker(combined):
                    continue

                status = "Listed"
                description = combined
                relevant_date = None

                if headers and len(headers) == len(cells):
                    pair = dict(zip(headers, cells))
                    for header, value in pair.items():
                        header_low = header.lower()
                        if "status" in header_low or "action" in header_low or "event" in header_low:
                            status = value or status
                        if "description" in header_low or "name" in header_low:
                            description = value or description
                        if "date" in header_low and not relevant_date:
                            relevant_date = try_parse_date(value)

                if relevant_date is None:
                    all_dates = collect_dates_from_text(combined)
                    relevant_date = all_dates[0] if all_dates else None

                if date_in_range(relevant_date, start_date, end_date):
                    records.append(
                        ListingRecord(
                            ticker=ticker,
                            source="FINRA",
                            status=status,
                            description=description[:400],
                            relevant_date=relevant_date,
                            raw_excerpt=combined[:800],
                        )
                    )
        return records
