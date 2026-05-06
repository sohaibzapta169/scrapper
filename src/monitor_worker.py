from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from src.models import AlertEvent, AlertSource, MonitorConfig
from src.scraper import FinraScraper, OtcMarketsScraper
from src.scraper.utils import normalize_ticker


class MonitorWorker(QObject):
    alert_confirmed = Signal(object)  # AlertEvent
    log_message = Signal(str)
    running_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._config: MonitorConfig | None = None
        self._finra = FinraScraper()
        self._otc = OtcMarketsScraper()
        self._alerted_keys: set[str] = set()

    def start(self, config: MonitorConfig) -> None:
        if self.is_running:
            return
        self._config = config
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.running_changed.emit(True)
        self.log_message.emit(
            f"Monitoring started for {len(config.tickers)} ticker(s), interval={config.interval_seconds}s"
        )

    def stop(self) -> None:
        if not self.is_running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=4)
        self._thread = None
        self.running_changed.emit(False)
        self.log_message.emit("Monitoring stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        assert self._config is not None
        while not self._stop_event.is_set():
            started = time.time()
            for ticker in self._config.tickers:
                if self._stop_event.is_set():
                    break
                try:
                    self._process_ticker(ticker)
                except Exception as exc:  # noqa: BLE001
                    self.log_message.emit(f"[{ticker}] monitor error: {exc}")

            elapsed = time.time() - started
            delay = max(1, self._config.interval_seconds - int(elapsed))
            for _ in range(delay):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _process_ticker(self, ticker: str) -> None:
        assert self._config is not None
        ticker = normalize_ticker(ticker)
        finra_records = self._finra.fetch_ticker(
            ticker, self._config.finra_start_date, self._config.finra_end_date
        )
        otc_records = self._otc.fetch_ticker(
            ticker, self._config.otc_start_date, self._config.otc_end_date
        )
        source = self._resolve_source(finra_records, otc_records)
        if source is None:
            self.log_message.emit(
                f"[{ticker}] no match (FINRA rows in range: {len(finra_records)}, "
                f"OTC rows in range: {len(otc_records)})"
            )
            return

        # Mandatory second confirmation step before any alert.
        finra_confirm = self._finra.fetch_ticker(
            ticker, self._config.finra_start_date, self._config.finra_end_date
        )
        otc_confirm = self._otc.fetch_ticker(
            ticker, self._config.otc_start_date, self._config.otc_end_date
        )
        source_confirm = self._resolve_source(finra_confirm, otc_confirm)
        if source_confirm != source:
            self.log_message.emit(f"[{ticker}] first pass mismatch after re-check, skipped")
            return

        if not self._has_overlap(finra_records, finra_confirm) and source in (AlertSource.FINRA, AlertSource.BOTH):
            self.log_message.emit(f"[{ticker}] FINRA no stable overlap across verification, skipped")
            return
        if not self._has_overlap(otc_records, otc_confirm) and source in (AlertSource.OTC, AlertSource.BOTH):
            self.log_message.emit(f"[{ticker}] OTC no stable overlap across verification, skipped")
            return

        description = self._build_description(finra_confirm, otc_confirm, source_confirm)
        event = AlertEvent(
            ticker=ticker,
            source=source_confirm,
            description=description,
            event_time=datetime.now(),
            finra_records=finra_confirm,
            otc_records=otc_confirm,
        )
        key = event.dedupe_key()
        if key in self._alerted_keys:
            self.log_message.emit(f"[{ticker}] duplicate confirmed event ignored")
            return

        self._alerted_keys.add(key)
        self.alert_confirmed.emit(event)
        self.log_message.emit(f"[{ticker}] confirmed alert emitted ({source_confirm.value})")

    def _resolve_source(self, finra_records: list, otc_records: list) -> AlertSource | None:
        has_finra = bool(finra_records)
        has_otc = bool(otc_records)
        if has_finra and has_otc:
            return AlertSource.BOTH
        if has_finra:
            return AlertSource.FINRA
        if has_otc:
            return AlertSource.OTC
        return None

    def _has_overlap(self, first: list, second: list) -> bool:
        if not first and not second:
            return True
        sig_first = {item.signature() for item in first}
        sig_second = {item.signature() for item in second}
        return bool(sig_first.intersection(sig_second))

    def _build_description(self, finra_records: list, otc_records: list, source: AlertSource) -> str:
        if source == AlertSource.FINRA and finra_records:
            return finra_records[0].description
        if source == AlertSource.OTC and otc_records:
            return otc_records[0].description
        if finra_records and otc_records:
            return f"FINRA: {finra_records[0].description} | OTC: {otc_records[0].description}"
        return "Listing match confirmed"
