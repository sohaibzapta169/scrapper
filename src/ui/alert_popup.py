from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect,
)

from src.models import AlertEvent, AlertSource

if TYPE_CHECKING:
    from src.alert_manager import AlertManager


def _source_colors(source: AlertSource) -> tuple[str, str, str]:
    """Return (bg_color, text_color, border_color) for a given source."""
    mapping = {
        AlertSource.FINRA: ("#1d4ed8", "#dbeafe", "#3b82f6"),
        AlertSource.OTC:   ("#0d9488", "#ccfbf1", "#14b8a6"),
        AlertSource.BOTH:  ("#7c3aed", "#ede9fe", "#8b5cf6"),
    }
    return mapping.get(source, ("#475569", "#f1f5f9", "#94a3b8"))


def _source_label(source: AlertSource) -> str:
    labels = {
        AlertSource.FINRA: "FINRA Daily List",
        AlertSource.OTC:   "OTC Markets",
        AlertSource.BOTH:  "FINRA + OTC Markets",
    }
    return labels.get(source, source.value)


class ListingAlertPopup(QDialog):
    """Non-modal, topmost summary of a confirmed listing alert."""

    def __init__(
        self,
        parent,
        event: AlertEvent,
        alert_manager: AlertManager | None = None,
        auto_close_ms: int = 25000,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        self._alert_manager = alert_manager
        self.setModal(False)
        self.setWindowTitle(f"Alert — {event.ticker}")
        self.setMinimumWidth(500)
        self.resize(580, 420)

        self._build_ui(event)

        if auto_close_ms > 0:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._dismiss)
            self._timer.start(auto_close_ms)

            # countdown label update every second
            self._remaining_ms = auto_close_ms
            self._tick_timer = QTimer(self)
            self._tick_timer.setInterval(1000)
            self._tick_timer.timeout.connect(self._tick_countdown)
            self._tick_timer.start()

    def _build_ui(self, event: AlertEvent) -> None:
        bg_col, text_col, border_col = _source_colors(event.source)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Accent banner ──────────────────────────────────────────────────
        banner = QWidget()
        banner.setFixedHeight(6)
        banner.setStyleSheet(f"background: {bg_col}; border-radius: 0px;")
        root.addWidget(banner)

        # ── Main content area ──────────────────────────────────────────────
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(22, 18, 22, 16)
        body_layout.setSpacing(14)
        root.addWidget(body_widget)

        # ── Source + ticker row ────────────────────────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        source_badge = QLabel(_source_label(event.source))
        source_badge.setStyleSheet(
            f"""
            QLabel {{
                background: {bg_col};
                color: #ffffff;
                border-radius: 5px;
                padding: 3px 10px;
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.6px;
            }}
            """
        )

        ticker_label = QLabel(event.ticker)
        ticker_label.setStyleSheet(
            f"""
            QLabel {{
                color: {bg_col};
                font-weight: 800;
                font-size: 22px;
                letter-spacing: 1.5px;
            }}
            """
        )

        header_row.addWidget(ticker_label)
        header_row.addSpacing(4)
        header_row.addWidget(source_badge)
        header_row.addStretch(1)

        self._countdown_label = QLabel("")
        self._countdown_label.setStyleSheet(
            "color: #94a3b8; font-size: 10px; font-weight: 500;"
        )
        header_row.addWidget(self._countdown_label)

        body_layout.addLayout(header_row)

        # ── Timestamp ─────────────────────────────────────────────────────
        when = QLabel(event.event_time.strftime("%Y-%m-%d  %H:%M:%S"))
        when.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 500;")
        body_layout.addWidget(when)

        # ── Status Indicators Section (like OTC Markets reference) ───────
        status_section = QFrame()
        status_section.setStyleSheet("""
            QFrame {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
        """)
        status_layout = QVBoxLayout(status_section)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(10)

        # Section title
        status_title = QLabel("Status Indicators")
        status_title.setStyleSheet("font-weight: 700; font-size: 12px; color: #334155; background: transparent;")
        status_layout.addWidget(status_title)

        # Collect data from all records
        grace_period_date = None
        all_statuses = []
        finra_event_types = []
        
        # From OTC records
        for record in event.otc_records:
            if record.grace_period_end:
                grace_period_date = record.grace_period_end
            if record.status:
                all_statuses.append(record.status)
        
        # From FINRA records
        for record in event.finra_records:
            if record.event_type:
                finra_event_types.append(record.event_type)
            if record.status:
                all_statuses.append(record.status)
        all_statuses = list(dict.fromkeys(all_statuses))

        # Create indicator widgets directly
        indicators_container = QWidget()
        indicators_layout = QVBoxLayout(indicators_container)
        indicators_layout.setContentsMargins(0, 0, 0, 0)
        indicators_layout.setSpacing(8)

        # 0. STATUS INDICATOR (single combined value like client reference asks)
        tier_keywords = ("pink limited", "pink current", "pink no information", "otcqx", "otcqb", "expert market", "grey market", "pink")
        indicator_values = []
        for s in all_statuses:
            low = s.lower()
            if any(t in low for t in tier_keywords):
                continue
            indicator_values.append(s)
        if indicator_values:
            indicators_layout.addWidget(
                self._make_indicator_label("Status Indicator", " / ".join(indicator_values[:3]), "#0f766e")
            )

        # 1. GRACE PERIOD with date (most important - show first)
        if grace_period_date:
            gp_label = self._make_indicator_label(
                "Grace Period", 
                f"Yes, Last Day: {grace_period_date.strftime('%m/%d/%Y')}",
                "#b45309"
            )
            indicators_layout.addWidget(gp_label)

        # 2. DARK OR DEFUNCT
        has_dark = any("dark" in s.lower() for s in all_statuses)
        if has_dark:
            dark_label = self._make_indicator_label("Dark or Defunct", "Yes", "#dc2626")
            indicators_layout.addWidget(dark_label)

        # 3. MARKET TIER
        market_tier = None
        for s in all_statuses:
            if s.lower() in tier_keywords or any(t in s.lower() for t in tier_keywords):
                market_tier = s
                break
        if market_tier:
            tier_label = self._make_indicator_label("Market Tier", market_tier, "#7c3aed")
            indicators_layout.addWidget(tier_label)

        # 4. FINRA EVENT TYPE
        if finra_event_types:
            for evt in finra_event_types[:2]:
                finra_label = self._make_indicator_label("FINRA Event", evt, "#1e40af")
                indicators_layout.addWidget(finra_label)

        # 5. BANKRUPTCY
        has_bankruptcy = any("bankrupt" in s.lower() for s in all_statuses)
        if has_bankruptcy:
            bank_label = self._make_indicator_label("Bankruptcy", "Filed", "#92400e")
            indicators_layout.addWidget(bank_label)

        # 6. CAVEAT EMPTOR
        has_caveat = any("caveat" in s.lower() for s in all_statuses)
        if has_caveat:
            caveat_label = self._make_indicator_label("Caveat Emptor", "Warning", "#b91c1c")
            indicators_layout.addWidget(caveat_label)

        # 7. SHELL RISK
        has_shell = any("shell" in s.lower() for s in all_statuses)
        if has_shell:
            shell_label = self._make_indicator_label("Shell Risk", "Warning", "#c2410c")
            indicators_layout.addWidget(shell_label)

        # If no indicators found at all, show all raw statuses
        if indicators_layout.count() == 0 and all_statuses:
            for status in all_statuses[:4]:
                status_label = self._make_indicator_label("Status", status, "#475569")
                indicators_layout.addWidget(status_label)

        status_layout.addWidget(indicators_container)
        body_layout.addWidget(status_section)

        # ── Divider ───────────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"color: {border_col}; background: {border_col}; max-height: 1px; border: none;")
        divider.setFixedHeight(1)
        body_layout.addWidget(divider)

        # ── Description ───────────────────────────────────────────────────
        desc = QTextEdit()
        desc.setReadOnly(True)
        desc.setPlainText(event.description)
        desc.setMinimumHeight(90)
        desc.setMaximumHeight(140)
        desc.setStyleSheet(
            """
            QTextEdit {
                border: none;
                background: transparent;
                color: #374151;
                font-size: 12px;
                line-height: 1.6;
                padding: 0;
            }
            """
        )
        body_layout.addWidget(desc)

        # ── Button row ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.setDefault(True)
        dismiss_btn.setMinimumWidth(100)
        dismiss_btn.setMinimumHeight(34)
        dismiss_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {bg_col};
                color: #ffffff;
                border: none;
                border-radius: 7px;
                padding: 7px 20px;
                font-weight: 700;
                font-size: 12px;
                letter-spacing: 0.2px;
            }}
            QPushButton:hover {{
                background: {border_col};
            }}
            QPushButton:pressed {{
                background: {bg_col};
                padding-top: 8px;
                padding-bottom: 6px;
            }}
            """
        )
        dismiss_btn.clicked.connect(self._dismiss)
        btn_row.addWidget(dismiss_btn)

        body_layout.addLayout(btn_row)

        # ── Outer window styling ──────────────────────────────────────────
        self.setStyleSheet(
            f"""
            QDialog {{
                background: #ffffff;
                border: 1.5px solid {border_col};
                border-radius: 12px;
            }}
            """
        )

    def _make_indicator_label(self, label: str, value: str, color: str) -> QLabel:
        """Create a simple indicator label with label and value on one line."""
        text = f"<b style='color:#475569;'>{label}:</b>  <span style='color:{color}; font-weight:700;'>{value}</span>"
        lbl = QLabel(text)
        lbl.setStyleSheet("""
            QLabel {
                font-size: 13px;
                padding: 6px 10px;
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
            }
        """)
        return lbl

    def _tick_countdown(self) -> None:
        self._remaining_ms -= 1000
        if self._remaining_ms > 0:
            secs = (self._remaining_ms + 999) // 1000
            self._countdown_label.setText(f"auto-close {secs}s")
        else:
            self._countdown_label.setText("")
            self._tick_timer.stop()

    def _dismiss(self) -> None:
        """Stop sound and close the popup."""
        if hasattr(self, "_timer"):
            self._timer.stop()
        if hasattr(self, "_tick_timer"):
            self._tick_timer.stop()
        if self._alert_manager is not None:
            self._alert_manager.stop_sound()
        self.close()