from __future__ import annotations

import re
from datetime import date

import cloudscraper
from bs4 import BeautifulSoup

from src.models import ListingRecord
from src.scraper.utils import collect_dates_from_text, date_in_range, normalize_ticker


class OtcMarketsScraper:
    OVERVIEW_URL = "https://www.otcmarkets.com/stock/{ticker}/overview"
    QUOTE_URL = "https://www.otcmarkets.com/stock/{ticker}/quote"

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
        records: list[ListingRecord] = []

        # Fetch Overview page
        overview_html = self._fetch_page(self.OVERVIEW_URL.format(ticker=ticker))
        # Fetch Quote page (has eligibility/grace period info)
        quote_html = self._fetch_page(self.QUOTE_URL.format(ticker=ticker))
        rendered_text = ""

        if not overview_html and not quote_html:
            # Last resort: JS-rendered fetch
            rendered_text = self._fetch_rendered_text_firefox(ticker)
            if not rendered_text:
                return []

        # OTC can return a generic marketing page when blocked/challenged.
        # In that case, do not emit misleading records (like false "Pink Limited").
        if not self._looks_like_ticker_page(overview_html, ticker) and not self._looks_like_ticker_page(quote_html, ticker):
            rendered_text = self._fetch_rendered_text_firefox(ticker)
            if not rendered_text:
                return []

        # Parse both pages
        overview_soup = BeautifulSoup(overview_html, "html.parser") if overview_html else None
        quote_soup = BeautifulSoup(quote_html, "html.parser") if quote_html else None

        combined_text = ""
        title_text = ""

        if overview_soup:
            title = overview_soup.select_one("title")
            title_text = title.get_text(" ", strip=True) if title else ""
            combined_text += overview_soup.get_text(" ", strip=True).lower()

        if quote_soup:
            combined_text += " " + quote_soup.get_text(" ", strip=True).lower()
        if rendered_text:
            combined_text += " " + rendered_text.lower()

        # Detect market tier from page content
        tier_found = None
        for kw in self.TIER_KEYWORDS:
            if kw in combined_text:
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

        # Look for warning/status keywords (excluding grace period - handled separately)
        status_found = []
        for kw in self.STATUS_KEYWORDS:
            if kw == "grace period":
                continue
            if kw in combined_text:
                status = self._classify_status(kw)
                if status not in status_found:
                    status_found.append(status)
                    idx = combined_text.find(kw)
                    context = combined_text[max(0, idx - 50) : idx + 150]
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

        # Extract Grace Period end date from Quote page (more reliable)
        grace_end_date = self._extract_grace_period_date(quote_html or overview_html or "")
        if not grace_end_date and rendered_text:
            grace_end_date = self._extract_grace_period_date_from_text(rendered_text)

        if grace_end_date:
            records.append(
                ListingRecord(
                    ticker=ticker,
                    source="OTC",
                    status="Grace Period",
                    description=f"{ticker} - Grace Period ends {grace_end_date.strftime('%m/%d/%Y')}",
                    relevant_date=grace_end_date,
                    raw_excerpt=f"Last Day of Grace Period: {grace_end_date.strftime('%m/%d/%Y')}",
                    grace_period_end=grace_end_date,
                )
            )
        elif "grace period" in combined_text:
            # Fallback: grace period mentioned but no specific date found
            grace_pattern = re.compile(
                r"grace\s+period[^.]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})",
                re.I,
            )
            matches = grace_pattern.findall(overview_html or quote_html or "")
            for match in matches[:2]:
                dates = collect_dates_from_text(match)
                if dates:
                    records.append(
                        ListingRecord(
                            ticker=ticker,
                            source="OTC",
                            status="Grace Period",
                            description=f"{ticker} - Grace period deadline: {match}",
                            relevant_date=dates[0],
                            raw_excerpt=match,
                            grace_period_end=dates[0],
                        )
                    )
                    break

        # Filter by date range and deduplicate
        unique: dict[str, ListingRecord] = {}
        for record in records:
            if record.relevant_date is None or date_in_range(record.relevant_date, start_date, end_date):
                unique[record.signature()] = record

        return list(unique.values())

    def _fetch_page(self, url: str) -> str:
        """Fetch a page and return HTML content, or empty string on failure."""
        try:
            resp = self.scraper.get(url, timeout=self.timeout_seconds)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return ""

    def _extract_grace_period_date(self, html: str) -> date | None:
        """Extract 'Last Day of Grace Period' date from Quote page HTML."""
        if not html:
            return None

        # Pattern 1: "Last Day of Grace Period: MM/DD/YYYY"
        pattern1 = re.compile(
            r"last\s+day\s+of\s+grace\s+period[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            re.I,
        )
        match = pattern1.search(html)
        if match:
            dates = collect_dates_from_text(match.group(1))
            if dates:
                return dates[0]

        # Pattern 2: "Grace Period: Yes, Last Day of Grace Period: MM/DD/YYYY"
        pattern2 = re.compile(
            r"grace\s+period[^<]*?(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            re.I,
        )
        match = pattern2.search(html)
        if match:
            dates = collect_dates_from_text(match.group(1))
            if dates:
                return dates[0]

        return None

    def _looks_like_ticker_page(self, html: str, ticker: str) -> bool:
        """Best-effort check that HTML is actually for the requested ticker page."""
        if not html:
            return False
        low = html.lower()
        t = ticker.lower()
        # Typical ticker-page markers seen in OTC HTML/metadata.
        markers = (
            f"/stock/{t}/",
            f"stock / {t} /",
            f"market activity / stock / {t} /",
            f">{t}<",
            f"symbol\":\"{t}\"",
            f"symbol={t}",
            f"quote {t}",
        )
        return any(m in low for m in markers)

    def _extract_grace_period_date_from_text(self, text: str) -> date | None:
        if not text:
            return None
        match = re.search(r"last\s+day\s+of\s+grace\s+period[:\s]*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
        if match:
            dates = collect_dates_from_text(match.group(1))
            if dates:
                return dates[0]
        return None

    def _fetch_rendered_text_firefox(self, ticker: str) -> str:
        """Fallback: render page with Playwright Firefox and extract body text."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return ""

        url = self.QUOTE_URL.format(ticker=ticker)
        try:
            with sync_playwright() as p:
                browser = p.firefox.launch(headless=True)
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4500)
                text = page.inner_text("body")
                browser.close()
                return text or ""
        except Exception:
            return ""

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
