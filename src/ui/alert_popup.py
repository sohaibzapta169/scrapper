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
        self.setMinimumWidth(460)
        self.resize(540, 300)

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