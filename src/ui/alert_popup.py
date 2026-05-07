from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from src.models import AlertEvent

if TYPE_CHECKING:
    from src.alert_manager import AlertManager


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
        self.setMinimumWidth(420)
        self.resize(520, 260)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 16, 18, 16)

        head = QLabel(f"<b>{event.source.value}</b> · <span style='color:#5a7ec2'>{event.ticker}</span>")
        head.setTextFormat(Qt.RichText)
        layout.addWidget(head)

        when = QLabel(event.event_time.strftime("%Y-%m-%d %H:%M:%S"))
        when.setObjectName("muted")
        layout.addWidget(when)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(event.description)
        body.setMinimumHeight(120)
        layout.addWidget(body)

        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Dismiss")
        ok.setDefault(True)
        ok.clicked.connect(self._dismiss)
        row.addWidget(ok)
        layout.addLayout(row)

        if auto_close_ms > 0:
            QTimer.singleShot(auto_close_ms, self._dismiss)

    def _dismiss(self) -> None:
        """Stop sound and close the popup."""
        if self._alert_manager is not None:
            self._alert_manager.stop_sound()
        self.close()
