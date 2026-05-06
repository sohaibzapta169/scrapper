from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class AlertSource(str, Enum):
    FINRA = "FINRA"
    OTC = "OTC"
    BOTH = "FINRA + OTC"


@dataclass(slots=True)
class ListingRecord:
    ticker: str
    source: str
    status: str
    description: str
    relevant_date: date | None = None
    raw_excerpt: str = ""

    def signature(self) -> str:
        date_part = self.relevant_date.isoformat() if self.relevant_date else "no-date"
        return f"{self.ticker}|{self.source}|{self.status}|{self.description}|{date_part}"


@dataclass(slots=True)
class AlertEvent:
    ticker: str
    source: AlertSource
    description: str
    event_time: datetime
    finra_records: list[ListingRecord] = field(default_factory=list)
    otc_records: list[ListingRecord] = field(default_factory=list)

    def dedupe_key(self) -> str:
        base = f"{self.ticker}|{self.source.value}|{self.description}"
        date_values = []
        for record in self.finra_records + self.otc_records:
            if record.relevant_date:
                date_values.append(record.relevant_date.isoformat())
        dates = ",".join(sorted(set(date_values)))
        return f"{base}|{dates}"


@dataclass(slots=True)
class MonitorConfig:
    tickers: list[str]
    interval_seconds: int = 30
    start_date: date | None = None
    end_date: date | None = None
