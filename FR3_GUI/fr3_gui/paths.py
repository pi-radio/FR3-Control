"""Where to put files the app writes at runtime (settings, logs).

Deliberately not __file__-relative: a packaged onefile build's __file__
resolves under a fresh temp dir every launch, and a onedir install may not
be writable at all. platformdirs gives the OS-appropriate persistent
location instead (%APPDATA%, ~/Library/Application Support, ~/.local/share)."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "FR3-Board-Control"


def app_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))
