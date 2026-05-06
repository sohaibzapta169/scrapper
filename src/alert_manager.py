from __future__ import annotations

import platform
import threading
from typing import Callable

from src.models import AlertEvent, AlertSource

try:
    from plyer import notification  # type: ignore
except Exception:  # noqa: BLE001
    notification = None

if platform.system().lower().startswith("win"):
    import winsound


class AlertManager:
    def __init__(self, ui_notify_callback: Callable[[str, str], None] | None = None) -> None:
        self._ui_notify_callback = ui_notify_callback

    def dispatch(self, event: AlertEvent) -> None:
        title = f"{event.source.value} Listing Alert: {event.ticker}"
        body = f"{event.description}\n{event.event_time.strftime('%Y-%m-%d %H:%M:%S')}"
        self._show_notification(title, body)
        threading.Thread(target=self._play_sound, args=(event.source,), daemon=True).start()

    def _show_notification(self, title: str, body: str) -> None:
        if self._ui_notify_callback:
            self._ui_notify_callback(title, body)
        if notification:
            try:
                notification.notify(title=title, message=body, app_name="Financial Listings Monitor", timeout=6)
            except Exception:  # noqa: BLE001
                pass

    def _play_sound(self, source: AlertSource) -> None:
        if platform.system().lower().startswith("win"):
            try:
                if source == AlertSource.FINRA:
                    winsound.Beep(880, 220)  # Sound A
                elif source == AlertSource.OTC:
                    winsound.Beep(660, 320)  # Sound B
                else:
                    winsound.Beep(1040, 180)  # Sound C (start)
                    winsound.Beep(1320, 180)
                return
            except Exception:  # noqa: BLE001
                pass
