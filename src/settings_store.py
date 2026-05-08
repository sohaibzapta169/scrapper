from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


def _config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "FinancialListingsMonitor"
    return Path.home() / ".config" / "financial-listings-monitor"


def settings_file_path() -> Path:
    return _config_dir() / "settings.json"


@dataclass
class AppSettings:
    tickers_text: str = ""
    interval_seconds: int = 30
    finra_start_iso: str | None = None
    finra_end_iso: str | None = None
    dark_mode: bool = False
    font_size: int = 11
    # Empty string = use bundled default (`src/ringtone/pager_alert_tone.mp3`).
    alert_sound_path: str = ""
    # FINRA event type filters (list of enabled event types); None or empty = all events
    finra_event_types: list[str] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> AppSettings:
        merged = asdict(cls())
        legacy_sound = ""
        for k in ("sound_both_path", "sound_finra_path", "sound_otc_path"):
            v = data.get(k)
            if v and str(v).strip():
                legacy_sound = str(v).strip()
                break
        for key, value in data.items():
            if key in merged:
                merged[key] = value
        if not str(merged.get("alert_sound_path") or "").strip() and legacy_sound:
            merged["alert_sound_path"] = legacy_sound
        # Ensure finra_event_types is a list or None
        evt = merged.get("finra_event_types")
        if evt is not None and not isinstance(evt, list):
            merged["finra_event_types"] = None
        return cls(**merged)


def load_settings() -> AppSettings:
    path = settings_file_path()
    if not path.is_file():
        return AppSettings()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return AppSettings()
        return AppSettings.from_json_dict(data)
    except (OSError, json.JSONDecodeError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(settings.to_json_dict(), indent=2, ensure_ascii=False)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
