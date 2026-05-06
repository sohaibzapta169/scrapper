from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.alert_manager import AlertManager
from src.models import AlertEvent, MonitorConfig
from src.monitor_worker import MonitorWorker
from src.scraper.utils import normalize_ticker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Financial Listings Monitoring Tool")
        self.resize(1020, 720)

        self.worker = MonitorWorker()
        self.worker.alert_confirmed.connect(self._on_alert)
        self.worker.log_message.connect(self._append_log)
        self.worker.running_changed.connect(self._on_running_changed)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.tray_icon.setVisible(True)
        self.tray_icon.activated.connect(self._on_tray_activated)

        self.alert_manager = AlertManager(ui_notify_callback=self._notify_ui)
        self._build_ui()
        self._apply_light_theme()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker.is_running:
            self.worker.stop()
        self.tray_icon.hide()
        event.accept()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header_card = QFrame()
        header_card.setObjectName("headerCard")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(10)
        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        title = QLabel("Financial Listings Monitoring Tool")
        title.setObjectName("mainTitle")
        subtitle = QLabel("Real-time FINRA + OTC monitoring with verification")
        subtitle.setObjectName("subTitle")
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap, stretch=1)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusBadge")
        self.status_label.setProperty("state", "idle")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumWidth(90)
        header_layout.addWidget(self.status_label)
        layout.addWidget(header_card)

        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(14, 14, 14, 14)
        controls_layout.setSpacing(10)

        controls_form = QFormLayout()
        controls_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        controls_form.setHorizontalSpacing(14)
        controls_form.setVerticalSpacing(10)
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText("e.g. AAPL, TSLA, ABCD")
        self.ticker_input.setClearButtonEnabled(True)
        controls_form.addRow("Tickers:", self.ticker_input)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(30)
        self.interval_spin.setSuffix(" sec")
        controls_form.addRow("Polling interval:", self.interval_spin)

        self.start_date_input = QDateEdit()
        self.start_date_input.setCalendarPopup(True)
        start_default = date.today().replace(day=1)
        self.start_date_input.setDate(QDate(start_default.year, start_default.month, start_default.day))
        controls_form.addRow("Date start:", self.start_date_input)

        self.end_date_input = QDateEdit()
        self.end_date_input.setCalendarPopup(True)
        end_default = date.today()
        self.end_date_input.setDate(QDate(end_default.year, end_default.month, end_default.day))
        controls_form.addRow("Date end:", self.end_date_input)

        style_row = QHBoxLayout()
        self.theme_toggle = QCheckBox("Dark mode")
        self.theme_toggle.toggled.connect(self._on_theme_toggle)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 22)
        self.font_size_spin.setValue(10)
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        style_row.addWidget(self.theme_toggle)
        style_row.addWidget(QLabel("Font size"))
        style_row.addWidget(self.font_size_spin)
        style_row.addStretch(1)
        controls_form.addRow("Display:", style_row)

        controls_layout.addLayout(controls_form)

        button_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Monitoring")
        self.start_btn.setObjectName("primaryButton")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_monitoring)
        self.stop_btn.clicked.connect(self._stop_monitoring)
        button_row.addWidget(self.start_btn)
        button_row.addWidget(self.stop_btn)
        button_row.addStretch(1)
        controls_layout.addLayout(button_row)
        layout.addWidget(controls_card)

        history_card = QFrame()
        history_card.setObjectName("card")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(14, 12, 14, 14)
        history_layout.setSpacing(8)
        history_label = QLabel("Alert History")
        history_label.setObjectName("sectionTitle")
        history_layout.addWidget(history_label)
        self.alert_history = QListWidget()
        history_layout.addWidget(self.alert_history)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 12, 14, 14)
        log_layout.setSpacing(8)
        log_label = QLabel("System Log")
        log_label.setObjectName("sectionTitle")
        log_layout.addWidget(log_label)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(history_card)
        splitter.addWidget(log_card)
        splitter.setSizes([260, 320])
        layout.addWidget(splitter, stretch=1)

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

    def _start_monitoring(self) -> None:
        tickers = [
            normalize_ticker(part)
            for part in self.ticker_input.text().split(",")
            if normalize_ticker(part)
        ]
        if not tickers:
            QMessageBox.warning(self, "Missing tickers", "Please provide at least one ticker.")
            return

        start_q = self.start_date_input.date().toPython()
        end_q = self.end_date_input.date().toPython()
        if start_q > end_q:
            QMessageBox.warning(self, "Invalid date range", "Start date must be before end date.")
            return

        config = MonitorConfig(
            tickers=tickers,
            interval_seconds=self.interval_spin.value(),
            start_date=start_q,
            end_date=end_q,
        )
        self.worker.start(config)

    def _stop_monitoring(self) -> None:
        self.worker.stop()

    def _on_alert(self, event: AlertEvent) -> None:
        self.alert_manager.dispatch(event)
        text = (
            f"{event.event_time.strftime('%H:%M:%S')} | {event.ticker} | "
            f"{event.source.value} | {event.description}"
        )
        item = QListWidgetItem(text)
        self.alert_history.insertItem(0, item)

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}")

    def _on_running_changed(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("Running" if running else "Idle")
        self.status_label.setProperty("state", "running" if running else "idle")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _notify_ui(self, title: str, body: str) -> None:
        self.tray_icon.showMessage(title, body, QSystemTrayIcon.Information, 5000)

    def _on_theme_toggle(self, is_dark: bool) -> None:
        if is_dark:
            self._apply_dark_theme()
        else:
            self._apply_light_theme()

    def _on_font_size_changed(self, value: int) -> None:
        font = QFont(self.font())
        font.setPointSize(value)
        self.setFont(font)

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #141824;
                color: #e9eef9;
                font-size: 10pt;
            }
            QFrame#headerCard {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #222a3e, stop:1 #1a2131);
                border: 1px solid #313d57;
                border-radius: 12px;
            }
            QFrame#card {
                background: #1a2131;
                border: 1px solid #313d57;
                border-radius: 12px;
            }
            QLabel#mainTitle { font-size: 14pt; font-weight: 700; color: #f2f6ff; background: transparent; }
            QLabel#subTitle { color: #aeb9d3; background: transparent; }
            QLabel#sectionTitle { font-size: 11pt; font-weight: 600; color: #e2e9f9; background: transparent; }
            QLabel#statusBadge {
                border: 1px solid #3f4f74;
                border-radius: 12px;
                padding: 4px 10px;
                font-weight: 600;
                background: #24304a;
                color: #d6e4ff;
            }
            QLabel#statusBadge[state="running"] {
                background: #173826;
                color: #8ff0b2;
                border: 1px solid #2d7c52;
            }
            QLabel#statusBadge[state="idle"] {
                background: #3b2e1f;
                color: #f6d28d;
                border: 1px solid #7f6136;
            }
            QLineEdit, QPlainTextEdit, QListWidget, QAbstractSpinBox {
                background: #0f1524;
                border: 1px solid #334466;
                border-radius: 8px;
                padding: 6px;
                color: #f2f6ff;
                selection-background-color: #3f63a3;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QAbstractSpinBox:focus {
                border: 1px solid #5f8be0;
            }
            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
                width: 20px;
                border: none;
                border-left: 1px solid #334466;
                background: #1d2640;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
                background: #2b3d67;
            }
            QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {
                background: #1a2845;
            }
            QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow, QDateEdit::down-arrow {
                width: 9px;
                height: 9px;
            }
            QDateEdit::drop-down {
                width: 24px;
                border: none;
                border-left: 1px solid #334466;
                background: #1d2640;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QDateEdit::drop-down:hover {
                background: #2b3d67;
            }
            QDateEdit::drop-down:pressed {
                background: #1a2845;
            }
            QCalendarWidget QWidget {
                background: #10182a;
                color: #e8efff;
            }
            QCalendarWidget QToolButton {
                background: #253250;
                border: 1px solid #3c4f75;
                border-radius: 6px;
                padding: 4px 8px;
                color: #eff4ff;
                font-weight: 600;
            }
            QCalendarWidget QAbstractItemView {
                background: #0f1524;
                border: 1px solid #334466;
                selection-background-color: #3f63a3;
                color: #eff4ff;
            }
            QPushButton, QToolButton {
                background: #253250;
                border: 1px solid #3c4f75;
                border-radius: 8px;
                padding: 8px 14px;
                color: #eff4ff;
                font-weight: 600;
                min-height: 18px;
            }
            QPushButton:hover, QToolButton:hover { background: #2f4068; }
            QPushButton:pressed, QToolButton:pressed { background: #1d2944; }
            QPushButton#primaryButton {
                background: #2663d5;
                border: 1px solid #3f7ceb;
            }
            QPushButton#primaryButton:hover { background: #2f72ef; }
            QPushButton:disabled, QToolButton:disabled {
                color: #8a96b1;
                background: #1a2338;
                border-color: #2c3650;
            }
            """
        )

    def _apply_light_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f3f6fb;
                color: #162134;
                font-size: 10pt;
            }
            QFrame#headerCard {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #edf4ff, stop:1 #dde9ff);
                border: 1px solid #c7d7f7;
                border-radius: 12px;
            }
            QFrame#card {
                background: #ffffff;
                border: 1px solid #d8e1f1;
                border-radius: 12px;
            }
            QLabel#mainTitle { font-size: 14pt; font-weight: 700; color: #1d2e4b; background: transparent; }
            QLabel#subTitle { color: #557095; background: transparent; }
            QLabel#sectionTitle { font-size: 11pt; font-weight: 600; color: #2a3d5f; background: transparent; }
            QLabel#statusBadge {
                border: 1px solid #bfd0ee;
                border-radius: 12px;
                padding: 4px 10px;
                font-weight: 600;
                background: #f2f7ff;
                color: #32598f;
            }
            QLabel#statusBadge[state="running"] {
                background: #e8f9ef;
                color: #1f7a45;
                border: 1px solid #9bdbb5;
            }
            QLabel#statusBadge[state="idle"] {
                background: #fff8e7;
                color: #8f6a20;
                border: 1px solid #efd998;
            }
            QLineEdit, QPlainTextEdit, QListWidget, QAbstractSpinBox {
                background: #ffffff;
                border: 1px solid #c9d7ed;
                border-radius: 8px;
                padding: 6px;
                selection-background-color: #a7c3f5;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QAbstractSpinBox:focus {
                border: 1px solid #4e84db;
            }
            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
                width: 20px;
                border: none;
                border-left: 1px solid #c9d7ed;
                background: #edf2fb;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
                background: #dfe9fb;
            }
            QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {
                background: #d4e2fa;
            }
            QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow, QDateEdit::down-arrow {
                width: 9px;
                height: 9px;
            }
            QDateEdit::drop-down {
                width: 24px;
                border: none;
                border-left: 1px solid #c9d7ed;
                background: #edf2fb;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QDateEdit::drop-down:hover {
                background: #dfe9fb;
            }
            QDateEdit::drop-down:pressed {
                background: #d4e2fa;
            }
            QCalendarWidget QWidget {
                background: #f7faff;
                color: #223757;
            }
            QCalendarWidget QToolButton {
                background: #eff3fb;
                border: 1px solid #c7d5ee;
                border-radius: 6px;
                padding: 4px 8px;
                color: #233553;
                font-weight: 600;
            }
            QCalendarWidget QAbstractItemView {
                background: #ffffff;
                border: 1px solid #c9d7ed;
                selection-background-color: #a7c3f5;
                color: #233553;
            }
            QPushButton, QToolButton {
                background: #eff3fb;
                border: 1px solid #c7d5ee;
                border-radius: 8px;
                padding: 8px 14px;
                color: #233553;
                font-weight: 600;
                min-height: 18px;
            }
            QPushButton:hover, QToolButton:hover { background: #e5ecf9; }
            QPushButton:pressed, QToolButton:pressed { background: #dce7fb; }
            QPushButton#primaryButton {
                background: #2f74eb;
                border: 1px solid #3f81f3;
                color: #ffffff;
            }
            QPushButton#primaryButton:hover { background: #2267dd; }
            QPushButton:disabled, QToolButton:disabled {
                color: #8ca0bf;
                background: #eef2f9;
                border-color: #d5deec;
            }
            """
        )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.showNormal()
            self.activateWindow()
