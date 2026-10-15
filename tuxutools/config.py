"""Configuration and on-disk locations for TuxuTools.

Mirrors the directory intent of the original Windows 3uTools layout
(``files/``, ``backup/``, firmware cache) but rooted under the XDG data
directory so a Linux install stays self-contained.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

APP_NAME = "tuxutools"

_XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
_XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def default_data_dir() -> Path:
    return Path(os.environ.get("TUXUTOOLS_DATA", _XDG_DATA / APP_NAME))


def default_cache_dir() -> Path:
    return Path(os.environ.get("TUXUTOOLS_CACHE", _XDG_CACHE / APP_NAME))


def default_config_dir() -> Path:
    return Path(os.environ.get("TUXUTOOLS_CONFIG", _XDG_CONFIG / APP_NAME))


@dataclass
class Settings:
    """Runtime settings for the core library."""

    data_dir: Path = field(default_factory=default_data_dir)
    cache_dir: Path = field(default_factory=default_cache_dir)
    config_dir: Path = field(default_factory=default_config_dir)
    backend: str = field(default_factory=lambda: os.environ.get("TUXUTOOLS_BACKEND", "auto"))
    usbmux_address: Optional[str] = field(
        default_factory=lambda: os.environ.get("TUXUTOOLS_USBMUX", None)
    )

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def firmware_dir(self) -> Path:
        return self.data_dir / "firmware"

    @property
    def payload_dir(self) -> Path:
        return self.data_dir / "payloads"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.cache_dir,
            self.config_dir,
            self.backup_dir,
            self.firmware_dir,
            self.payload_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def bundled_files_dir() -> Optional[Path]:
    """Locate the extracted 3uTools ``files/`` payload directory, if present.

    The REA investigation found resources such as ``files/jb90.7z`` and
    ``files/ipa/*.ipa`` embedded in the original installer.  When the user has
    the extracted tree available we expose it so the jailbreak and app modules
    can reuse those payloads instead of re-deriving them.
    """

    override = os.environ.get("TUXUTOOLS_BUNDLED_FILES")
    if override:
        p = Path(override)
        return p if p.is_dir() else None

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "extracted" / "files"
        if candidate.is_dir():
            return candidate
    return None
