"""Shared dataclasses used across the TuxuTools core.

These are deliberately plain dataclasses so they can be serialised to JSON,
moved across threads and rendered by either the CLI or the Qt GUI without
depending on any device library.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class ConnectionType(str, Enum):
    USB = "USB"
    NETWORK = "Network"
    UNKNOWN = "Unknown"


@dataclass
class DeviceRef:
    """A device as reported by the transport layer (before lockdown)."""

    udid: str
    connection_type: ConnectionType = ConnectionType.UNKNOWN
    serial: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["connection_type"] = self.connection_type.value
        return d


@dataclass
class DeviceInfo:
    """Merged lockdown + diagnostics view of a device."""

    udid: str
    name: Optional[str] = None
    model: Optional[str] = None
    product_type: Optional[str] = None
    device_class: Optional[str] = None
    ios_version: Optional[str] = None
    build_version: Optional[str] = None
    serial_number: Optional[str] = None
    imei: Optional[str] = None
    phone_number: Optional[str] = None
    battery_level: Optional[int] = None
    battery_charging: Optional[bool] = None
    storage_total: Optional[int] = None
    storage_free: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        bits = [self.name or "Unknown device", self.model or self.product_type or "?"]
        if self.ios_version:
            bits.append(f"iOS {self.ios_version}")
        return " - ".join(bits)


@dataclass
class FileEntry:
    """One entry in an AFC directory listing."""

    name: str
    path: str
    is_dir: bool = False
    size: int = 0
    modified: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AppInfo:
    """An installed application (from installation_proxy)."""

    bundle_identifier: str
    name: Optional[str] = None
    version: Optional[str] = None
    app_type: Optional[str] = None
    path: Optional[str] = None
    container: Optional[str] = None
    size: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackupInfo:
    """A local iTunes-style backup on disk."""

    udid: str
    directory: str
    date: Optional[str] = None
    product_version: Optional[str] = None
    product_type: Optional[str] = None
    device_name: Optional[str] = None
    encrypted: bool = False
    size: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FirmwareInfo:
    """An IPSW firmware image (local or from a catalog)."""

    identifier: str
    version: str
    build: str
    url: Optional[str] = None
    local_path: Optional[str] = None
    signed: Optional[bool] = None
    size: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Progress:
    """A progress report emitted by long running operations."""

    operation: str
    fraction: Optional[float] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
