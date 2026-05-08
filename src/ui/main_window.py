from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.alert_manager import AlertManager
from src.models import AlertEvent, FINRA_EVENT_TYPES, MonitorConfig
from src.monitor_worker import MonitorWorker
from src.scraper.utils import normalize_ticker
from src.ringtone_paths import default_alert_sound_path, ringtone_dir
from src.settings_store import AppSettings, load_settings, parse_iso_date, save_settings


def _section_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("sectionTitle")
    return lab


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("hint")
    lab.setWordWrap(True)
    return lab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Financial Listings Monitoring Tool")
        self.resize(1100, 820)
        self.setMinimumSize(880, 640)

        self.worker = MonitorWorker()
        self.worker.alert_confirmed.connect(self._on_alert)
        self.worker.log_message.connect(self._append_log)
        self.worker.running_changed.connect(self._on_running_changed)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray_icon.setVisible(True)
        self.tray_icon.activated.connect(self._on_tray_activated)

        self.alert_manager = AlertManager(parent=self, ui_notify_callback=self._notify_ui)

        self._build_ui()
        self._load_settings_into_ui()
        self._sync_typography()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist_settings()
        if self.worker.is_running:
            self.worker.stop()
        self.tray_icon.hide()
        event.accept()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 18, 20, 12)
        layout.setSpacing(14)

        # —— Header ——
        header = QFrame()
        header.setObjectName("headerCard")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 18, 20, 18)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.main_title = QLabel("Financial Listings Monitor")
        self.main_title.setObjectName("mainTitle")
        self.sub_title = QLabel("FINRA daily list + OTC Markets status · verified alerts")
        self.sub_title.setObjectName("subTitle")
        titles.addWidget(self.main_title)
        titles.addWidget(self.sub_title)
        hl.addLayout(titles, stretch=1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        row_top = QHBoxLayout()
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusBadge")
        self.status_label.setProperty("state", "idle")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumWidth(96)
        row_top.addStretch(1)
        row_top.addWidget(self.status_label)
        actions.addLayout(row_top)

        row_btn = QHBoxLayout()
        row_btn.setSpacing(10)
        self.start_btn = QPushButton("▶  Start monitoring")
        self.start_btn.setObjectName("primaryButton")
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.setEnabled(False)
        self.save_btn = QPushButton("Save preferences")
        self.save_btn.setObjectName("ghostButton")
        self.start_btn.clicked.connect(self._start_monitoring)
        self.stop_btn.clicked.connect(self._stop_monitoring)
        self.save_btn.clicked.connect(self._persist_settings)
        row_btn.addWidget(self.start_btn)
        row_btn.addWidget(self.stop_btn)
        row_btn.addWidget(self.save_btn)
        actions.addLayout(row_btn)
        hl.addLayout(actions)
        layout.addWidget(header)

        # —— Watchlist ——
        watch = QFrame()
        watch.setObjectName("card")
        wl = QVBoxLayout(watch)
        wl.setContentsMargins(18, 16, 18, 16)
        wl.setSpacing(8)
        wl.addWidget(_section_title("Watchlist"))
        wl.addWidget(_hint("Comma-separated tickers to watch (e.g. ABCD, XYZ). Matching ignores extra spaces."))
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText("Ticker symbols…")
        self.ticker_input.setClearButtonEnabled(True)
        self.ticker_input.setMinimumHeight(36)
        wl.addWidget(self.ticker_input)
        layout.addWidget(watch)

        # —— Schedule ——
        sched = QFrame()
        sched.setObjectName("card")
        sl = QVBoxLayout(sched)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(10)
        sl.addWidget(_section_title("Polling"))
        grid_s = QGridLayout()
        grid_s.setColumnStretch(1, 1)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(30)
        self.interval_spin.setSuffix(" sec")
        self.interval_spin.setMinimumHeight(32)
        grid_s.addWidget(QLabel("Interval"), 0, 0)
        grid_s.addWidget(self.interval_spin, 0, 1)
        sl.addLayout(grid_s)
        sl.addWidget(_hint("How long to wait between full passes across all tickers. First pass runs immediately."))
        layout.addWidget(sched)

        # —— Date range (FINRA only) ——
        date_card = QFrame()
        date_card.setObjectName("card")
        dl = QVBoxLayout(date_card)
        dl.setContentsMargins(18, 16, 18, 16)
        dl.setSpacing(10)
        dl.addWidget(_section_title("Date range (FINRA Daily List)"))
        dl.addWidget(
            _hint(
                "Date range filter applies only to FINRA Daily List rows. "
                "OTC status checks (Grace Period, Dark/Defunct, Market Tier) are always live/current."
            )
        )
        ug = QGridLayout()
        ug.setHorizontalSpacing(12)
        ug.setVerticalSpacing(8)
        self.unified_start = QDateEdit()
        self.unified_end = QDateEdit()
        for w in (self.unified_start, self.unified_end):
            w.setCalendarPopup(True)
            w.setMinimumHeight(32)
        ug.addWidget(QLabel("From"), 0, 0)
        ug.addWidget(self.unified_start, 0, 1)
        ug.addWidget(QLabel("To"), 1, 0)
        ug.addWidget(self.unified_end, 1, 1)
        dl.addLayout(ug)

        layout.addWidget(date_card)

        # —— FINRA Event Type Filters ——
        event_filter_card = QFrame()
        event_filter_card.setObjectName("card")
        ef_layout = QVBoxLayout(event_filter_card)
        ef_layout.setContentsMargins(18, 16, 18, 16)
        ef_layout.setSpacing(10)
        ef_layout.addWidget(_section_title("FINRA Event Type Filters"))
        ef_layout.addWidget(
            _hint(
                "Select which FINRA event types to monitor. Uncheck events you want to ignore. "
                "If none are checked, all events are included."
            )
        )
        
        # Create checkboxes for each event type in a grid layout
        self.event_type_checkboxes: dict[str, QCheckBox] = {}
        event_grid = QGridLayout()
        event_grid.setHorizontalSpacing(16)
        event_grid.setVerticalSpacing(6)
        
        for idx, event_type in enumerate(FINRA_EVENT_TYPES):
            cb = QCheckBox(event_type)
            cb.setChecked(True)  # Default: all checked
            self.event_type_checkboxes[event_type] = cb
            row = idx // 2
            col = idx % 2
            event_grid.addWidget(cb, row, col)
        
        ef_layout.addLayout(event_grid)
        
        # Select All / Deselect All buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        select_all_btn = QPushButton("Select All")
        select_all_btn.setObjectName("smallButton")
        select_all_btn.clicked.connect(self._select_all_event_types)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setObjectName("smallButton")
        deselect_all_btn.clicked.connect(self._deselect_all_event_types)
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(deselect_all_btn)
        btn_row.addStretch(1)
        ef_layout.addLayout(btn_row)
        
        layout.addWidget(event_filter_card)

        # —— Alert sound ——
        sound_card = QFrame()
        sound_card.setObjectName("card")
        snd = QVBoxLayout(sound_card)
        snd.setContentsMargins(18, 16, 18, 16)
        snd.setSpacing(12)
        snd.addWidget(_section_title("Alert sound"))
        snd.addWidget(
            _hint(
                "One sound for every alert (FINRA, OTC, or both). Default: bundled pager tone. "
                "Browse copies the file into the app ringtone folder. Settings are stored in settings.json."
            )
        )
        sound_row = QHBoxLayout()
        sound_row.setSpacing(10)
        self.alert_sound_edit = QLineEdit()
        self.alert_sound_edit.setReadOnly(True)
        self.alert_sound_edit.setMinimumHeight(32)
        self.alert_sound_edit.setPlaceholderText("Default bundled sound")
        browse_sound = QPushButton("Browse…")
        browse_sound.setObjectName("smallButton")
        clear_sound = QPushButton("Reset to default")
        clear_sound.setObjectName("smallButton")
        test_sound = QPushButton("Test")
        test_sound.setObjectName("accentButton")
        browse_sound.clicked.connect(self._browse_alert_sound)
        clear_sound.clicked.connect(self._reset_alert_sound)
        test_sound.clicked.connect(self._test_alert_sound)
        sound_row.addWidget(self.alert_sound_edit, stretch=1)
        sound_row.addWidget(browse_sound)
        sound_row.addWidget(clear_sound)
        sound_row.addWidget(test_sound)
        snd.addLayout(sound_row)

        test_alert_row = QHBoxLayout()
        test_alert_row.setSpacing(10)
        test_alert_btn = QPushButton("⚡  Send Test Alert")
        test_alert_btn.setObjectName("warningButton")
        test_alert_btn.clicked.connect(self._send_test_alert)
        test_alert_row.addWidget(test_alert_btn)
        test_alert_row.addWidget(_hint("Triggers a fake alert to test in-window details, sound, and history."))
        test_alert_row.addStretch(1)
        snd.addLayout(test_alert_row)
        layout.addWidget(sound_card)

        # —— Appearance ——
        look = QFrame()
        look.setObjectName("card")
        ll = QVBoxLayout(look)
        ll.setContentsMargins(18, 16, 18, 16)
        ll.setSpacing(10)
        ll.addWidget(_section_title("Appearance"))
        row = QHBoxLayout()
        self.theme_toggle = QCheckBox("Dark mode")
        self.theme_toggle.toggled.connect(self._on_theme_toggle)
        row.addWidget(self.theme_toggle)
        row.addSpacing(16)
        row.addWidget(QLabel("Base font size"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(9, 24)
        self.font_size_spin.setValue(11)
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        self.font_size_spin.setMinimumHeight(30)
        row.addWidget(self.font_size_spin)
        row.addStretch(1)
        ll.addLayout(row)
        layout.addWidget(look)

        layout.addSpacing(8)

        # —— Latest Match Details (in-window; replaces popup) ——
        details_card = QFrame()
        details_card.setObjectName("card")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(16, 14, 16, 14)
        details_layout.setSpacing(8)
        details_layout.addWidget(_section_title("Latest match details"))
        details_layout.addWidget(
            _hint("When conditions are met, details are shown here (no separate popup window).")
        )
        self.latest_match_output = QPlainTextEdit()
        self.latest_match_output.setReadOnly(True)
        self.latest_match_output.setMinimumHeight(140)
        self.latest_match_output.setPlaceholderText(
            "No matches yet.\n"
            "This section will show Grace Period (Yes/No + Date), market status, and FINRA reason/event details."
        )
        details_layout.addWidget(self.latest_match_output)
        layout.addWidget(details_card)

        # —— History + log ——
        history_card = QFrame()
        history_card.setObjectName("card")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(16, 14, 16, 14)
        history_layout.setSpacing(8)
        history_layout.addWidget(_section_title("Alert history"))
        self.alert_history = QListWidget()
        self.alert_history.setMinimumHeight(96)
        self.alert_history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        history_layout.addWidget(self.alert_history)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 14, 16, 14)
        log_layout.setSpacing(8)
        log_layout.addWidget(_section_title("Activity log"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(120)
        self.log_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        log_layout.addWidget(self.log_output)

        log_splitter = QSplitter(Qt.Vertical)
        log_splitter.setChildrenCollapsible(True)
        log_splitter.addWidget(history_card)
        log_splitter.addWidget(log_card)
        log_splitter.setSizes([160, 200])
        layout.addWidget(log_splitter, stretch=1)

        tray_menu = self.tray_icon.contextMenu()
        if tray_menu is None:
            from PySide6.QtWidgets import QMenu
            tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)

    def _select_all_event_types(self) -> None:
        for cb in self.event_type_checkboxes.values():
            cb.setChecked(True)

    def _deselect_all_event_types(self) -> None:
        for cb in self.event_type_checkboxes.values():
            cb.setChecked(False)

    def _get_selected_event_types(self) -> list[str] | None:
        """Return list of selected event types, or None if all are selected (no filtering)."""
        selected = [et for et, cb in self.event_type_checkboxes.items() if cb.isChecked()]
        if len(selected) == len(FINRA_EVENT_TYPES) or len(selected) == 0:
            return None  # No filtering needed
        return selected

    def _set_event_type_checkboxes(self, event_types: list[str] | None) -> None:
        """Set checkbox states from saved settings."""
        if event_types is None:
            # All selected by default
            for cb in self.event_type_checkboxes.values():
                cb.setChecked(True)
        else:
            for et, cb in self.event_type_checkboxes.items():
                cb.setChecked(et in event_types)

    def _browse_alert_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select alert sound",
            str(Path.home()),
            "Audio (*.wav *.mp3 *.aac *.m4a *.flac);;All files (*.*)",
        )
        if not path:
            return
        src = Path(path)
        dest_dir = ringtone_dir()
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
        except OSError as exc:
            QMessageBox.warning(self, "Ringtone folder", f"Could not copy file into ringtone folder:\n{exc}")
            return
        self.alert_sound_edit.setText(str(dest.resolve()))
        self._sync_alert_sound()

    def _reset_alert_sound(self) -> None:
        self.alert_sound_edit.setText(self._display_default_sound_path())
        self._sync_alert_sound()

    def _display_default_sound_path(self) -> str:
        p = Path(default_alert_sound_path())
        return str(p) if p.is_file() else ""

    def _effective_alert_sound_path(self) -> str:
        raw = self.alert_sound_edit.text().strip()
        if raw and Path(raw).is_file():
            return str(Path(raw).resolve())
        default_p = default_alert_sound_path()
        return default_p if Path(default_p).is_file() else ""

    def _alert_sound_for_storage(self) -> str:
        cur = self.alert_sound_edit.text().strip()
        if not cur:
            return ""
        default_p = default_alert_sound_path()
        try:
            if Path(cur).resolve() == Path(default_p).resolve():
                return ""
        except OSError:
            pass
        return str(Path(cur).resolve())

    def _test_alert_sound(self) -> None:
        self._sync_alert_sound()
        if not self._effective_alert_sound_path():
            QMessageBox.warning(
                self,
                "Sound file",
                "No audio file found. Add pager_alert_tone.mp3 under src/ringtone/ or browse for a file.",
            )
            return
        self.alert_manager.play_test()

    def _send_test_alert(self) -> None:
        from datetime import timedelta
        from src.models import AlertEvent, AlertSource, ListingRecord

        # Create a test grace period end date (e.g., 7 days from today)
        test_grace_end = date.today() + timedelta(days=7)

        # FINRA record with event type
        fake_finra_record = ListingRecord(
            ticker="TEST",
            source="FINRA",
            status="Addition",
            description="Test FINRA daily list entry.",
            relevant_date=date.today(),
            raw_excerpt="Sample FINRA data for testing purposes.",
            event_type="Additions",
        )
        
        # OTC record with market tier
        fake_otc_tier = ListingRecord(
            ticker="TEST",
            source="OTC",
            status="Pink Limited",
            description="Pink Limited Market tier.",
            relevant_date=date.today(),
            raw_excerpt="Market tier information.",
        )
        
        # OTC record with Grace Period + end date
        fake_otc_grace = ListingRecord(
            ticker="TEST",
            source="OTC",
            status="Grace Period",
            description="Grace Period status detected.",
            relevant_date=date.today(),
            raw_excerpt="Grace period information.",
            grace_period_end=test_grace_end,
        )
        
        # OTC record with Dark/Defunct status
        fake_otc_dark = ListingRecord(
            ticker="TEST",
            source="OTC",
            status="Dark/Defunct",
            description="Dark or Defunct status detected.",
            relevant_date=date.today(),
            raw_excerpt="Dark/Defunct information.",
        )
        
        fake_event = AlertEvent(
            ticker="TEST",
            source=AlertSource.BOTH,
            description="Test listing match: FINRA Daily List + OTC Markets (Pink Limited, Grace Period, Dark/Defunct)",
            event_time=datetime.now(),
            finra_records=[fake_finra_record],
            otc_records=[fake_otc_tier, fake_otc_grace, fake_otc_dark],
        )
        self._on_alert(fake_event)
        self._append_log("[TEST] Fake alert triggered for UI testing")

    def _sync_alert_sound(self) -> None:
        self.alert_manager.set_alert_sound(self._effective_alert_sound_path())

    def _default_date_range(self) -> tuple[date, date]:
        return date(2015, 1, 1), date(2026, 12, 31)

    def _load_settings_into_ui(self) -> None:
        s = load_settings()
        self.ticker_input.setText(s.tickers_text)
        self.interval_spin.setValue(s.interval_seconds)

        d0, d1 = self._default_date_range()
        fs = parse_iso_date(s.finra_start_iso) or d0
        fe = parse_iso_date(s.finra_end_iso) or d1
        self.unified_start.setDate(QDate(fs.year, fs.month, fs.day))
        self.unified_end.setDate(QDate(fe.year, fe.month, fe.day))

        self.font_size_spin.setValue(s.font_size)
        self.theme_toggle.blockSignals(True)
        self.theme_toggle.setChecked(s.dark_mode)
        self.theme_toggle.blockSignals(False)
        if s.dark_mode:
            self._apply_dark_theme()
        else:
            self._apply_light_theme()

        stored = (s.alert_sound_path or "").strip()
        if stored and Path(stored).is_file():
            self.alert_sound_edit.setText(str(Path(stored).resolve()))
        else:
            self.alert_sound_edit.setText(self._display_default_sound_path())
        self._sync_alert_sound()

        # Load event type filters
        self._set_event_type_checkboxes(s.finra_event_types)

    def _gather_settings(self) -> AppSettings:
        u0 = self.unified_start.date().toPython()
        u1 = self.unified_end.date().toPython()
        fs, fe = u0, u1
        return AppSettings(
            tickers_text=self.ticker_input.text(),
            interval_seconds=self.interval_spin.value(),
            finra_start_iso=fs.isoformat(),
            finra_end_iso=fe.isoformat(),
            dark_mode=self.theme_toggle.isChecked(),
            font_size=self.font_size_spin.value(),
            alert_sound_path=self._alert_sound_for_storage(),
            finra_event_types=self._get_selected_event_types(),
        )

    def _persist_settings(self) -> None:
        try:
            save_settings(self._gather_settings())
            self._append_log("Preferences saved.")
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _start_monitoring(self) -> None:
        tickers = [
            normalize_ticker(part)
            for part in self.ticker_input.text().split(",")
            if normalize_ticker(part)
        ]
        if not tickers:
            QMessageBox.warning(self, "Watchlist", "Enter at least one ticker.")
            return

        f_start = self.unified_start.date().toPython()
        f_end = self.unified_end.date().toPython()
        if f_start > f_end:
            QMessageBox.warning(self, "Date range", "From must be on or before To.")
            return

        self._sync_alert_sound()
        self._persist_settings()

        config = MonitorConfig(
            tickers=tickers,
            interval_seconds=self.interval_spin.value(),
            finra_start_date=f_start,
            finra_end_date=f_end,
            finra_event_types=self._get_selected_event_types(),
        )
        self.worker.start(config)

    def _stop_monitoring(self) -> None:
        self.worker.stop()

    def _on_alert(self, event: AlertEvent) -> None:
        self._sync_alert_sound()
        # In-window alerting only (no custom popup window).
        self.alert_manager.play_alert_sound()
        self._render_latest_match(event)
        
        # Build display text with grace period end date if available
        text = (
            f"{event.event_time.strftime('%H:%M:%S')} | {event.ticker} | "
            f"{event.source.value} | {event.description}"
        )
        
        # Check for grace period end date in OTC records
        for record in event.otc_records:
            if record.grace_period_end:
                text += f" | Grace Period Ends: {record.grace_period_end.strftime('%m/%d/%Y')}"
                break
        
        self.alert_history.insertItem(0, QListWidgetItem(text))

    def _render_latest_match(self, event: AlertEvent) -> None:
        finra_reasons: list[str] = []
        for record in event.finra_records:
            reason = record.description.strip()
            if reason and reason not in finra_reasons:
                finra_reasons.append(reason)

        otc_statuses: list[str] = []
        market_tier = ""
        grace_end = None
        for record in event.otc_records:
            if record.grace_period_end and grace_end is None:
                grace_end = record.grace_period_end
            status = record.status.strip()
            if status and status not in otc_statuses:
                otc_statuses.append(status)
            if not market_tier and status.lower() in {
                "pink limited",
                "pink current",
                "pink no information",
                "otcqx",
                "otcqb",
                "expert market",
                "grey market",
                "pink",
            }:
                market_tier = status

        grace_yes = any("grace" in s.lower() for s in otc_statuses) or grace_end is not None
        grace_line = "Yes" if grace_yes else "No"
        grace_date_line = grace_end.strftime("%m/%d/%Y") if grace_end else "N/A"

        lines = [
            f"Ticker: {event.ticker}",
            f"Source: {event.source.value}",
            f"Detected at: {event.event_time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "OTC Status",
            f"- Grace Period: {grace_line}",
            f"- Grace Period Date: {grace_date_line if grace_yes else 'N/A'}",
            f"- Market Tier: {market_tier or 'N/A'}",
            f"- Status Indicators: {', '.join(otc_statuses) if otc_statuses else 'N/A'}",
            "",
            "Daily List (FINRA) Reason",
        ]
        if finra_reasons:
            lines.extend([f"- {r}" for r in finra_reasons[:6]])
        else:
            lines.append("- N/A")
        self.latest_match_output.setPlainText("\n".join(lines))

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {message}")

    def _on_running_changed(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("Running" if running else "Idle")
        self.status_label.setProperty("state", "running" if running else "idle")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _notify_ui(self, title: str, body: str) -> None:
        self.tray_icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 8000)

    def _on_theme_toggle(self, is_dark: bool) -> None:
        if is_dark:
            self._apply_dark_theme()
        else:
            self._apply_light_theme()
        self._sync_typography()

    def _on_font_size_changed(self, _value: int) -> None:
        self._sync_typography()

    def _sync_typography(self) -> None:
        size = self.font_size_spin.value()
        title_font = QFont("Segoe UI Variable", size + 5)
        if not title_font.exactMatch():
            title_font = QFont("Segoe UI", size + 5)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.main_title.setFont(title_font)

        sub_font = QFont("Segoe UI Variable", max(size - 1, 8))
        if not sub_font.exactMatch():
            sub_font = QFont("Segoe UI", max(size - 1, 8))
        self.sub_title.setFont(sub_font)

        base = QFont("Segoe UI Variable", size)
        if not base.exactMatch():
            base = QFont("Segoe UI", size)
        self.setFont(base)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def _asset_icon_url(self, filename: str) -> str:
        return str((Path(__file__).resolve().parents[2] / "assets" / "icons" / filename).resolve()).replace(
            "\\", "/"
        )

    def _apply_light_theme(self) -> None:
        # ── Refined light theme with a richer button palette ──────────────────
        # Primary   : vivid indigo-blue  #1d4ed8 → hover #2563eb
        # Danger    : rich crimson       #dc2626 → hover #ef4444
        # Warning   : amber-gold         #d97706 → hover #f59e0b
        # Accent    : teal               #0d9488 → hover #14b8a6
        # Ghost     : transparent + dash border
        # Small/sec : cool slate         #475569 → hover #334155
        style = """
            * { background: transparent; }
            QWidget { background: #f0f4f8; color: #1e293b; }
            QMainWindow { background: #f0f4f8; }
            QLabel { background: transparent; color: #1e293b; }

            QFrame#headerCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffffff, stop:0.6 #f8faff, stop:1 #eef2fb);
                border: 1px solid #c7d4e8;
                border-radius: 14px;
            }
            QFrame#card {
                background: #ffffff;
                border: 1px solid #dde4ef;
                border-radius: 12px;
            }

            QLabel#mainTitle  { color: #0f172a; font-weight: 700; }
            QLabel#subTitle   { color: #64748b; }
            QLabel#sectionTitle {
                font-weight: 700;
                color: #1e293b;
                letter-spacing: 0.3px;
            }
            QLabel#hint { color: #94a3b8; font-size: 10px; }

            /* ── Status badge ── */
            QLabel#statusBadge {
                border: 1.5px solid #c7d4e8;
                border-radius: 16px;
                padding: 5px 16px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.8px;
                background: #f1f5fb;
                color: #475569;
                text-transform: uppercase;
            }
            QLabel#statusBadge[state="running"] {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #dcfce7, stop:1 #d1fae5);
                color: #15803d;
                border-color: #86efac;
            }
            QLabel#statusBadge[state="idle"] {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #fef9c3, stop:1 #fef3c7);
                color: #92400e;
                border-color: #fcd34d;
            }

            /* ── Inputs ── */
            QLineEdit, QPlainTextEdit, QListWidget, QAbstractSpinBox, QDateEdit {
                background: #f8fafc;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                padding: 7px 11px;
                color: #1e293b;
                selection-background-color: #bfdbfe;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus,
            QAbstractSpinBox:focus, QDateEdit:focus {
                border: 1.5px solid #3b82f6;
                background: #ffffff;
            }
            QLineEdit:hover, QAbstractSpinBox:hover, QDateEdit:hover {
                border-color: #93c5fd;
            }

            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
                width: 22px; border: none;
                border-left: 1px solid #cbd5e1;
                background: transparent;
            }
            QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
                background: rgba(59, 130, 246, 0.10);
            }
            QDateEdit::drop-down {
                width: 26px; border: none;
                border-left: 1px solid #cbd5e1;
                background: transparent;
            }
            QDateEdit::drop-down:hover { background: rgba(59, 130, 246, 0.10); }
            QAbstractSpinBox::up-arrow {
                image: url("__UP_ICON__"); width: 10px; height: 10px;
            }
            QAbstractSpinBox::down-arrow, QDateEdit::down-arrow {
                image: url("__DOWN_ICON__"); width: 10px; height: 10px;
            }

            /* ── BASE button (secondary / default) ── */
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f8fafc, stop:1 #eef2f7);
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px 18px;
                font-weight: 600;
                color: #334155;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f1f5f9, stop:1 #e2e8f0);
                border-color: #94a3b8;
                color: #1e293b;
            }
            QPushButton:pressed {
                background: #dde4ef;
                border-color: #64748b;
            }
            QPushButton:disabled {
                color: #94a3b8;
                background: #f8fafc;
                border-color: #e2e8f0;
            }

            /* ── PRIMARY — indigo-blue "Start monitoring" ── */
            QPushButton#primaryButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #2563eb, stop:1 #1d4ed8);
                border: 1.5px solid #1d4ed8;
                border-bottom-color: #1a44be;
                border-radius: 8px;
                color: #ffffff;
                font-weight: 700;
                letter-spacing: 0.2px;
            }
            QPushButton#primaryButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                border-color: #3b82f6;
            }
            QPushButton#primaryButton:pressed {
                background: #1d4ed8;
                border-color: #1e40af;
            }
            QPushButton#primaryButton:disabled {
                background: #bfdbfe;
                border-color: #93c5fd;
                color: #eff6ff;
            }

            /* ── DANGER — crimson red "Stop" ── */
            QPushButton#dangerButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #ef4444, stop:1 #dc2626);
                border: 1.5px solid #dc2626;
                border-bottom-color: #b91c1c;
                border-radius: 8px;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton#dangerButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f87171, stop:1 #ef4444);
                border-color: #ef4444;
            }
            QPushButton#dangerButton:pressed {
                background: #dc2626;
                border-color: #b91c1c;
            }
            QPushButton#dangerButton:disabled {
                background: #fecaca;
                border-color: #fca5a5;
                color: #fff5f5;
            }

            /* ── WARNING — amber "Send Test Alert" ── */
            QPushButton#warningButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f59e0b, stop:1 #d97706);
                border: 1.5px solid #d97706;
                border-bottom-color: #b45309;
                border-radius: 8px;
                color: #ffffff;
                font-weight: 700;
                letter-spacing: 0.2px;
            }
            QPushButton#warningButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #fbbf24, stop:1 #f59e0b);
                border-color: #f59e0b;
            }
            QPushButton#warningButton:pressed {
                background: #d97706;
                border-color: #b45309;
            }

            /* ── ACCENT — teal "Test" (sound) ── */
            QPushButton#accentButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #14b8a6, stop:1 #0d9488);
                border: 1.5px solid #0d9488;
                border-bottom-color: #0f766e;
                border-radius: 8px;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton#accentButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #2dd4bf, stop:1 #14b8a6);
                border-color: #14b8a6;
            }
            QPushButton#accentButton:pressed {
                background: #0d9488;
                border-color: #0f766e;
            }

            /* ── GHOST — dashed "Save preferences" ── */
            QPushButton#ghostButton {
                background: transparent;
                border: 1.5px dashed #94a3b8;
                border-radius: 8px;
                color: #64748b;
                font-weight: 600;
            }
            QPushButton#ghostButton:hover {
                background: rgba(59, 130, 246, 0.06);
                border-color: #3b82f6;
                color: #2563eb;
            }
            QPushButton#ghostButton:pressed {
                background: rgba(59, 130, 246, 0.12);
            }

            /* ── SMALL — secondary action buttons ── */
            QPushButton#smallButton {
                padding: 6px 14px;
                font-size: 10px;
                font-weight: 600;
                color: #475569;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f8fafc, stop:1 #f1f5f9);
                border: 1.5px solid #cbd5e1;
                border-radius: 7px;
            }
            QPushButton#smallButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f1f5f9, stop:1 #e2e8f0);
                border-color: #94a3b8;
                color: #1e293b;
            }
            QPushButton#smallButton:pressed {
                background: #e2e8f0;
            }

            /* ── Checkbox ── */
            QCheckBox { spacing: 8px; background: transparent; }
            QCheckBox::indicator {
                width: 17px; height: 17px;
                border-radius: 5px;
                border: 1.5px solid #94a3b8;
                background: #ffffff;
            }
            QCheckBox::indicator:hover { border-color: #3b82f6; }
            QCheckBox::indicator:checked {
                border-color: #2563eb;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                image: url("__CHECK_ICON__");
            }

            /* ── Misc ── */
            QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
            QTextEdit {
                background: #f8fafc;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                color: #1e293b;
            }
            QGroupBox { background: transparent; }
            QSplitter::handle { background: #dde4ef; height: 2px; }

            /* ── Calendar popup ── */
            QCalendarWidget QWidget { background: #ffffff; color: #1e293b; }
            QCalendarWidget QToolButton {
                background: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 4px 8px;
                color: #334155;
                font-weight: 600;
            }
            QCalendarWidget QAbstractItemView {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                selection-background-color: #bfdbfe;
                color: #1e293b;
            }
        """
        self.setStyleSheet(
            style.replace("__UP_ICON__", self._asset_icon_url("chevron-up-dark.svg"))
            .replace("__DOWN_ICON__", self._asset_icon_url("chevron-down-dark.svg"))
            .replace("__CHECK_ICON__", self._asset_icon_url("check-dark.svg"))
        )

    def _apply_dark_theme(self) -> None:
        # ── Rich dark theme with matching coloured buttons ─────────────────────
        style = """
            * { background: transparent; }
            QWidget { background: #0b0f18; color: #e2e8f5; }
            QMainWindow { background: #0b0f18; }
            QLabel { background: transparent; color: #e2e8f5; }

            QFrame#headerCard {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #131b2e, stop:1 #0f1624);
                border: 1px solid #1e2d48;
                border-radius: 14px;
            }
            QFrame#card {
                background: #0f1520;
                border: 1px solid #1e2b40;
                border-radius: 12px;
            }

            QLabel#mainTitle  { color: #f0f6ff; font-weight: 700; }
            QLabel#subTitle   { color: #7a8fae; }
            QLabel#sectionTitle {
                font-weight: 700;
                color: #b8cceb;
                letter-spacing: 0.3px;
            }
            QLabel#hint { color: #4e6080; font-size: 10px; }

            /* ── Status badge ── */
            QLabel#statusBadge {
                border: 1.5px solid #253349;
                border-radius: 16px;
                padding: 5px 16px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.8px;
                background: #121a28;
                color: #7a9ccf;
            }
            QLabel#statusBadge[state="running"] {
                background: #0c2116;
                color: #4ade80;
                border-color: #166534;
            }
            QLabel#statusBadge[state="idle"] {
                background: #1e1708;
                color: #fbbf24;
                border-color: #713f12;
            }

            /* ── Inputs ── */
            QLineEdit, QPlainTextEdit, QListWidget, QAbstractSpinBox, QDateEdit {
                background: #080c14;
                border: 1.5px solid #1e2d48;
                border-radius: 8px;
                padding: 7px 11px;
                color: #e2e8f5;
                selection-background-color: #1e3a5f;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus,
            QAbstractSpinBox:focus, QDateEdit:focus {
                border: 1.5px solid #3b82f6;
                background: #0a1020;
            }
            QLineEdit:hover, QAbstractSpinBox:hover, QDateEdit:hover {
                border-color: #2d4a7a;
            }

            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
                width: 22px; border: none;
                border-left: 1px solid #1e2d48;
                background: transparent;
            }
            QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
                background: rgba(59, 130, 246, 0.15);
            }
            QDateEdit::drop-down {
                width: 26px; border: none;
                border-left: 1px solid #1e2d48;
                background: transparent;
            }
            QDateEdit::drop-down:hover { background: rgba(59, 130, 246, 0.15); }
            QAbstractSpinBox::up-arrow {
                image: url("__UP_ICON__"); width: 10px; height: 10px;
            }
            QAbstractSpinBox::down-arrow, QDateEdit::down-arrow {
                image: url("__DOWN_ICON__"); width: 10px; height: 10px;
            }

            /* ── BASE button ── */
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #192130, stop:1 #131c2c);
                border: 1.5px solid #253349;
                border-bottom-color: #0d1420;
                border-radius: 8px;
                padding: 8px 18px;
                font-weight: 600;
                color: #c0cfe8;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1f2e45, stop:1 #172438);
                border-color: #3a5078;
                color: #e2eeff;
            }
            QPushButton:pressed {
                background: #0f1824;
                border-color: #1e2d48;
            }
            QPushButton:disabled {
                color: #3a4a62;
                background: #0c1118;
                border-color: #182030;
            }

            /* ── PRIMARY ── */
            QPushButton#primaryButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #2563eb, stop:1 #1d4ed8);
                border: 1.5px solid #1d4ed8;
                border-bottom-color: #1a44be;
                color: #ffffff;
                font-weight: 700;
                letter-spacing: 0.2px;
            }
            QPushButton#primaryButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                border-color: #60a5fa;
            }
            QPushButton#primaryButton:pressed {
                background: #1d4ed8;
            }
            QPushButton#primaryButton:disabled {
                background: #1e3560;
                border-color: #1e3560;
                color: #3d5a8a;
            }

            /* ── DANGER ── */
            QPushButton#dangerButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #dc2626, stop:1 #b91c1c);
                border: 1.5px solid #b91c1c;
                border-bottom-color: #991b1b;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton#dangerButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #ef4444, stop:1 #dc2626);
                border-color: #f87171;
            }
            QPushButton#dangerButton:pressed {
                background: #991b1b;
            }
            QPushButton#dangerButton:disabled {
                background: #451515;
                border-color: #451515;
                color: #7a2020;
            }

            /* ── WARNING ── */
            QPushButton#warningButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #d97706, stop:1 #b45309);
                border: 1.5px solid #b45309;
                border-bottom-color: #92400e;
                color: #ffffff;
                font-weight: 700;
                letter-spacing: 0.2px;
            }
            QPushButton#warningButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #f59e0b, stop:1 #d97706);
                border-color: #fbbf24;
            }
            QPushButton#warningButton:pressed {
                background: #92400e;
            }

            /* ── ACCENT ── */
            QPushButton#accentButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #0d9488, stop:1 #0f766e);
                border: 1.5px solid #0f766e;
                border-bottom-color: #115e59;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton#accentButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #14b8a6, stop:1 #0d9488);
                border-color: #2dd4bf;
            }
            QPushButton#accentButton:pressed {
                background: #0f766e;
            }

            /* ── GHOST ── */
            QPushButton#ghostButton {
                background: transparent;
                border: 1.5px dashed #2d4060;
                border-radius: 8px;
                color: #6a85a8;
                font-weight: 600;
            }
            QPushButton#ghostButton:hover {
                background: rgba(59, 130, 246, 0.08);
                border-color: #3b82f6;
                color: #93c5fd;
            }
            QPushButton#ghostButton:pressed {
                background: rgba(59, 130, 246, 0.14);
            }

            /* ── SMALL ── */
            QPushButton#smallButton {
                padding: 6px 14px;
                font-size: 10px;
                font-weight: 600;
                color: #8aaccc;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #162030, stop:1 #101828);
                border: 1.5px solid #1e2d48;
                border-radius: 7px;
            }
            QPushButton#smallButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1e2e46, stop:1 #162038);
                border-color: #3a5078;
                color: #c0d8f0;
            }
            QPushButton#smallButton:pressed {
                background: #0f1824;
            }

            /* ── Checkbox ── */
            QCheckBox { spacing: 8px; background: transparent; }
            QCheckBox::indicator {
                width: 17px; height: 17px;
                border-radius: 5px;
                border: 1.5px solid #2d4060;
                background: transparent;
            }
            QCheckBox::indicator:hover { border-color: #3b82f6; }
            QCheckBox::indicator:checked {
                border-color: #2563eb;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                image: url("__CHECK_ICON__");
            }

            /* ── Misc ── */
            QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
            QTextEdit {
                background: #080c14;
                border: 1.5px solid #1e2d48;
                border-radius: 8px;
                color: #e2e8f5;
            }
            QGroupBox { background: transparent; }
            QSplitter::handle { background: #1a2438; height: 2px; }

            QCalendarWidget QWidget { background: #0b0f18; color: #e2e8f5; }
            QCalendarWidget QToolButton {
                background: #131c2c;
                border: 1px solid #1e2d48;
                border-radius: 5px;
                padding: 4px 8px;
                color: #c0cfe8;
                font-weight: 600;
            }
            QCalendarWidget QAbstractItemView {
                background: #080c14;
                border: 1px solid #1e2d48;
                selection-background-color: #1e3a5f;
                color: #e2e8f5;
            }
        """
        self.setStyleSheet(
            style.replace("__UP_ICON__", self._asset_icon_url("chevron-up-light.svg"))
            .replace("__DOWN_ICON__", self._asset_icon_url("chevron-down-light.svg"))
            .replace("__CHECK_ICON__", self._asset_icon_url("check-light.svg"))
        )