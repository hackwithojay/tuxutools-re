"""Device backend abstraction.

Everything above this layer (services, CLI, GUI) talks to an
:class:`DeviceBackend`.  The concrete implementation shipped with TuxuTools
wraps ``pymobiledevice3``; a deterministic :class:`~tuxutools.backends.mock.MockBackend`
is used for tests and for developing the UI without hardware.

All device methods are ``async`` because the underlying protocol stack is
asyncio based.  The synchronous wrappers live in :mod:`tuxutools.services`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Callable, Optional

from ..models import (
    AppInfo,
    DeviceInfo,
    DeviceRef,
    FileEntry,
    Progress,
)

ProgressCallback = Callable[[Progress], None]


def _emit(cb: Optional[ProgressCallback], operation: str, fraction: Optional[float], message: str = "") -> None:
    if cb is not None:
        cb(Progress(operation=operation, fraction=fraction, message=message))


class DeviceBackend(ABC):
    """Abstract access to iOS devices.

    Implementations must be safe to instantiate without a device connected;
    errors surface from the individual operations.
    """

    #: Short identifier, e.g. ``"pymobiledevice3"`` or ``"mock"``.
    name: str = "abstract"

    # -- lifecycle ---------------------------------------------------------

    async def close(self) -> None:  # pragma: no cover - default no-op
        """Release any pooled connections."""

    # -- device discovery / identity --------------------------------------

    @abstractmethod
    async def list_devices(self) -> list[DeviceRef]:
        """Return every device currently visible over the transport."""

    @abstractmethod
    async def get_info(self, udid: Optional[str] = None) -> DeviceInfo:
        """Return merged lockdown/diagnostics information for a device."""

    async def get_value(self, udid: Optional[str], key: str, domain: Optional[str] = None):
        raise NotImplementedError

    # -- filesystem (AFC) --------------------------------------------------

    @abstractmethod
    async def afc_listdir(self, udid: Optional[str], path: str) -> list[FileEntry]:
        ...

    async def afc_stat(self, udid: Optional[str], path: str) -> FileEntry:
        raise NotImplementedError

    async def afc_get(self, udid: Optional[str], remote: str) -> bytes:
        raise NotImplementedError

    async def afc_put(self, udid: Optional[str], remote: str, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    async def afc_pull(
        self, udid: Optional[str], remote: str, local: str,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        ...

    @abstractmethod
    async def afc_push(
        self, udid: Optional[str], local: str, remote: str,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        ...

    async def afc_rm(self, udid: Optional[str], path: str) -> None:
        raise NotImplementedError

    async def afc_mkdir(self, udid: Optional[str], path: str) -> None:
        raise NotImplementedError

    async def afc_rename(self, udid: Optional[str], src: str, dst: str) -> None:
        raise NotImplementedError

    # -- applications ------------------------------------------------------

    @abstractmethod
    async def list_apps(self, udid: Optional[str], app_type: str = "Any") -> list[AppInfo]:
        ...

    @abstractmethod
    async def install_app(
        self, udid: Optional[str], ipa_path: str, developer: bool = False,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        ...

    @abstractmethod
    async def uninstall_app(self, udid: Optional[str], bundle_identifier: str) -> None:
        ...

    # -- backup / restore --------------------------------------------------

    @abstractmethod
    async def backup(
        self, udid: Optional[str], destination: str, full: bool = True,
        password: str = "", progress: Optional[ProgressCallback] = None,
    ) -> None:
        ...

    @abstractmethod
    async def restore(
        self, udid: Optional[str], source: str, password: str = "",
        reboot: bool = True, progress: Optional[ProgressCallback] = None,
    ) -> None:
        ...

    async def backup_info(self, udid: Optional[str], source: str) -> dict:
        raise NotImplementedError

    # -- diagnostics / observability --------------------------------------

    async def diagnostics_info(self, udid: Optional[str]) -> dict:
        raise NotImplementedError

    async def screenshot(self, udid: Optional[str]) -> bytes:
        raise NotImplementedError

    async def syslog(self, udid: Optional[str]) -> AsyncIterator[str]:  # pragma: no cover
        raise NotImplementedError
        yield ""  # make this an async generator for type checkers

    # -- firmware ----------------------------------------------------------

    async def enter_recovery(self, udid: Optional[str]) -> None:
        raise NotImplementedError

    async def enter_dfu(self, udid: Optional[str]) -> None:
        raise NotImplementedError

    async def reboot(self, udid: Optional[str]) -> None:
        raise NotImplementedError

    async def flash_firmware(
        self, ipsw_path: str, progress: Optional[ProgressCallback] = None,
    ) -> None:
        raise NotImplementedError
