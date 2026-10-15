"""Synchronous application facade used by the CLI and the Qt GUI.

The device stack is asynchronous; :class:`TuxuTools` presents an ergonomic
blocking API and centralises progress reporting, path defaults and error
normalisation.  Each call creates a short-lived event loop, which keeps the
facade safe to use from worker threads.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from .backends import DeviceBackend, create_backend
from .config import Settings
from .models import (
    AppInfo,
    BackupInfo,
    DeviceInfo,
    DeviceRef,
    FileEntry,
    FirmwareInfo,
    Progress,
)
from .services import firmware as firmware_service
from .services import jailbreak as jailbreak_service

ProgressCallback = Callable[[Progress], None]


class TuxuTools:
    """One-stop facade over a device backend."""

    def __init__(self, settings: Optional[Settings] = None, backend: Optional[DeviceBackend] = None) -> None:
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.backend = backend or create_backend(self.settings)

    # -- low level ---------------------------------------------------------

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def close(self) -> None:
        try:
            self._run(self.backend.close())
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "TuxuTools":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- devices -----------------------------------------------------------

    def devices(self) -> list[DeviceRef]:
        return self._run(self.backend.list_devices())

    def info(self, udid: Optional[str] = None) -> DeviceInfo:
        return self._run(self.backend.get_info(udid))

    def reboot(self, udid: Optional[str] = None) -> None:
        self._run(self.backend.reboot(udid))

    def enter_recovery(self, udid: Optional[str] = None) -> None:
        self._run(self.backend.enter_recovery(udid))

    def diagnostics(self, udid: Optional[str] = None) -> dict:
        return self._run(self.backend.diagnostics_info(udid))

    def screenshot(self, udid: Optional[str] = None) -> bytes:
        return self._run(self.backend.screenshot(udid))

    # -- files -------------------------------------------------------------

    def list_dir(self, path: str = "/", udid: Optional[str] = None) -> list[FileEntry]:
        return self._run(self.backend.afc_listdir(udid, path))

    def get_file(self, remote: str, udid: Optional[str] = None) -> bytes:
        return self._run(self.backend.afc_get(udid, remote))

    def put_file(self, remote: str, data: bytes, udid: Optional[str] = None) -> None:
        self._run(self.backend.afc_put(udid, remote, data))

    def pull(self, remote: str, local: str, udid: Optional[str] = None,
             progress: Optional[ProgressCallback] = None) -> None:
        self._run(self.backend.afc_pull(udid, remote, local, progress))

    def push(self, local: str, remote: str, udid: Optional[str] = None,
             progress: Optional[ProgressCallback] = None) -> None:
        self._run(self.backend.afc_push(udid, local, remote, progress))

    def mkdir(self, path: str, udid: Optional[str] = None) -> None:
        self._run(self.backend.afc_mkdir(udid, path))

    def remove(self, path: str, udid: Optional[str] = None) -> None:
        self._run(self.backend.afc_rm(udid, path))

    def rename(self, src: str, dst: str, udid: Optional[str] = None) -> None:
        self._run(self.backend.afc_rename(udid, src, dst))

    # -- apps --------------------------------------------------------------

    def apps(self, app_type: str = "Any", udid: Optional[str] = None) -> list[AppInfo]:
        return self._run(self.backend.list_apps(udid, app_type))

    def install_ipa(self, ipa_path: str, udid: Optional[str] = None, developer: bool = False,
                    progress: Optional[ProgressCallback] = None) -> None:
        self._run(self.backend.install_app(udid, ipa_path, developer=developer, progress=progress))

    def uninstall(self, bundle_identifier: str, udid: Optional[str] = None) -> None:
        self._run(self.backend.uninstall_app(udid, bundle_identifier))

    # -- backup / restore --------------------------------------------------

    def backup(self, udid: Optional[str] = None, destination: Optional[str] = None,
               full: bool = True, password: str = "",
               progress: Optional[ProgressCallback] = None) -> str:
        dest = destination or str(self.settings.backup_dir / (udid or "default"))
        self._run(self.backend.backup(udid, dest, full=full, password=password, progress=progress))
        return dest

    def restore(self, source: str, udid: Optional[str] = None, password: str = "",
                reboot: bool = True, progress: Optional[ProgressCallback] = None) -> None:
        self._run(self.backend.restore(udid, source, password=password, reboot=reboot, progress=progress))

    def backup_info(self, source: str, udid: Optional[str] = None) -> dict:
        return self._run(self.backend.backup_info(udid, source))

    def list_local_backups(self) -> list[BackupInfo]:
        import json
        from datetime import datetime

        out: list[BackupInfo] = []
        for child in sorted(self.settings.backup_dir.glob("*")):
            if not child.is_dir():
                continue
            info = child / "Info.plist"
            name = version = product = None
            if info.is_file():
                try:
                    # Info.plist in an unencrypted backup is a binary plist; try json first
                    text = info.read_text(errors="ignore")
                    data = json.loads(text)
                    name = data.get("Device Name")
                    version = data.get("Product Version")
                    product = data.get("Product Type")
                except Exception:  # noqa: BLE001
                    pass
            out.append(
                BackupInfo(
                    udid=child.name,
                    directory=str(child),
                    date=datetime.fromtimestamp(child.stat().st_mtime).isoformat(timespec="seconds"),
                    product_version=version,
                    product_type=product,
                    device_name=name,
                    encrypted=(child / "Manifest.plist").exists(),
                )
            )
        return out

    # -- media -------------------------------------------------------------

    def export_photos(self, destination: str, udid: Optional[str] = None,
                      remote: str = "/DCIM",
                      progress: Optional[ProgressCallback] = None) -> int:
        """Copy the camera roll (or any remote dir) to *destination*.

        Returns the number of files transferred.
        """

        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        count = 0

        def walk(path: str) -> None:
            nonlocal count
            for entry in self.list_dir(path, udid=udid):
                if entry.is_dir:
                    walk(entry.path)
                else:
                    rel = entry.path.lstrip("/")
                    target = dest / rel
                    self.pull(entry.path, str(target), udid=udid)
                    count += 1
                    if progress:
                        progress(Progress(operation="export_photos", message=entry.path))

        walk(remote)
        return count

    def import_photo(self, local: str, udid: Optional[str] = None,
                     remote_dir: str = "/DCIM/100APPLE") -> None:
        """Upload a local file to the device camera roll/staging directory."""

        name = Path(local).name
        self.push(local, f"{remote_dir.rstrip('/')}/{name}", udid=udid)

    # -- firmware ----------------------------------------------------------

    def list_firmwares(self, product_type: str, only_signed: bool = False) -> list[FirmwareInfo]:
        return firmware_service.list_firmwares(product_type, only_signed=only_signed)

    def download_firmware(self, url: str, destination: Optional[str] = None,
                          progress: Optional[ProgressCallback] = None) -> Path:
        if destination is None:
            name = url.rstrip("/").split("/")[-1] or "firmware.ipsw"
            destination = str(self.settings.firmware_dir / name)
        return firmware_service.download(url, destination, progress=progress)

    def verify_firmware(self, ipsw_path: str, expected: Optional[str] = None) -> str:
        return firmware_service.verify(ipsw_path, expected)

    def flash_firmware(self, ipsw_path: str, erase: bool = False,
                       progress: Optional[ProgressCallback] = None) -> None:
        self._run(self.backend.flash_firmware(ipsw_path, progress=progress, erase=erase))

    # -- jailbreak ---------------------------------------------------------

    def jailbreak_tools(self):
        return jailbreak_service.detect_tools()

    def jailbreak_payloads(self):
        return jailbreak_service.bundled_payloads(self.settings)

    def supports_checkm8(self, product_type: Optional[str]) -> bool:
        return jailbreak_service.supports_checkm8(product_type)

    def jailbreak(self, method: str = "palera1n", rootless: bool = True,
                  progress: Optional[ProgressCallback] = None) -> int:
        if method == "palera1n":
            return jailbreak_service.run_palera1n(rootless=rootless, progress=progress)
        if method == "checkra1n":
            return jailbreak_service.run_checkra1n(progress=progress)
        raise ValueError(f"unknown jailbreak method: {method!r}")
