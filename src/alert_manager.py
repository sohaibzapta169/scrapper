from __future__ import annotations

import platform
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QUrl
from PySide6.QtWidgets import QApplication

from src.models import AlertEvent

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover
    QMediaPlayer = None  # type: ignore[misc, assignment]
    QAudioOutput = None  # type: ignore[misc, assignment]

try:
    from plyer import notification  # type: ignore
except Exception:  # noqa: BLE001
    notification = None

if platform.system().lower().startswith("win"):
    import winsound


class AlertManager(QObject):
    """Tray/desktop notifications plus one audible alert file for all match types."""

    def __init__(
        self,
        parent: QObject | None = None,
        ui_notify_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._ui_notify_callback = ui_notify_callback
        self._sound_path: str = ""
        self._player: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        if QMediaPlayer is not None and QAudioOutput is not None:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._audio_out.setVolume(1.0)

    def set_alert_sound(self, path: str) -> None:
        """Resolved filesystem path to an audio file, or empty to use fallbacks only."""
        self._sound_path = path.strip()

    def dispatch(self, event: AlertEvent) -> None:
        title = f"{event.source.value} Listing Alert: {event.ticker}"
        body = f"{event.description}\n{event.event_time.strftime('%Y-%m-%d %H:%M:%S')}"
        self._show_notification(title, body)
        self.play_alert_sound()

    def play_test(self) -> None:
        self.play_alert_sound()

    def stop_sound(self) -> None:
        """Stop any currently playing alert sound."""
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:  # noqa: BLE001
                pass

    def play_alert_sound(self) -> None:
        path = self._sound_path
        if path:
            resolved = Path(path)
            if resolved.is_file():
                if self._player is not None:
                    try:
                        self._player.stop()
                        self._player.setSource(QUrl.fromLocalFile(str(resolved.resolve())))
                        self._player.play()
                        return
                    except Exception:  # noqa: BLE001
                        pass
                if platform.system().lower().startswith("win") and str(resolved).lower().endswith(".wav"):
                    try:
                        winsound.PlaySound(str(resolved), winsound.SND_FILENAME | winsound.SND_ASYNC)
                        return
                    except Exception:  # noqa: BLE001
                        pass
        self._default_beep()

    def _show_notification(self, title: str, body: str) -> None:
        if self._ui_notify_callback:
            self._ui_notify_callback(title, body)
        if notification:
            try:
                notification.notify(title=title, message=body, app_name="Financial Listings Monitor", timeout=8)
            except Exception:  # noqa: BLE001
                pass

    def _default_beep(self) -> None:
        if platform.system().lower().startswith("win"):
            try:
                winsound.Beep(880, 220)
                return
            except Exception:  # noqa: BLE001
                pass
        app = QApplication.instance()
        if app is not None:
            app.beep()
