"""Bundled alert sound and user ringtone directory (under `src/ringtone/`)."""

from __future__ import annotations

from pathlib import Path

DEFAULT_ALERT_FILENAME = "pager_alert_tone.mp3"


def ringtone_dir() -> Path:
    return Path(__file__).resolve().parent / "ringtone"


def default_alert_sound_path() -> str:
    return str((ringtone_dir() / DEFAULT_ALERT_FILENAME).resolve())
