"""Concrete :class:`DeviceBackend` built on ``pymobiledevice3``.

``pymobiledevice3`` is the modern pure-Python reimplementation of the
libimobiledevice/usbmuxd stack.  It covers every protocol the original
Windows 3uTools used through Apple's MobileDevice framework (lockdown, AFC,
installation_proxy, mobilebackup2, diagnostics, screenshots, syslog,
recovery/restore) and works on Linux without needing the ``usbmuxd`` daemon
for USB access.
"""

from __future__ import annotations

import asyncio
import datetime
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from ..exceptions import (
    AfcError,
    AppError,
    BackupError,
    BackendUnavailableError,
    DeviceNotPairedError,
    FirmwareError,
    NoDeviceError,
    UnsupportedOperationError,
)
from ..models import (
    AppInfo,
    ConnectionType,
    DeviceInfo,
    DeviceRef,
    FileEntry,
    Progress,
)
from .base import DeviceBackend, ProgressCallback, _emit


def pmd3_available() -> bool:
    return importlib.util.find_spec("pymobiledevice3") is not None


def _require() -> None:
    if not pmd3_available():
        raise BackendUnavailableError(
            "pymobiledevice3 is not installed. Install it with: "
            "pip install pymobiledevice3"
        )


def _as_connection_type(raw: str) -> ConnectionType:
    value = (raw or "").lower()
    if value in ("usb",):
        return ConnectionType.USB
    if value in ("network", "ethernet", "wifi"):
        return ConnectionType.NETWORK
    return ConnectionType.UNKNOWN


class Pymobiledevice3Backend(DeviceBackend):
    name = "pymobiledevice3"

    def __init__(self, usbmux_address: Optional[str] = None) -> None:
        _require()
        self._usbmux_address = usbmux_address

    # -- helpers -----------------------------------------------------------

    async def _lockdown(self, udid: Optional[str]):
        from pymobiledevice3.lockdown import create_using_usbmux

        try:
            return await create_using_usbmux(
                serial=udid,
                usbmux_address=self._usbmux_address,
                autopair=True,
            )
        except Exception as exc:  # noqa: BLE001 - normalise backend errors
            msg = str(exc).lower()
            if "not paired" in msg or "pair" in msg:
                raise DeviceNotPairedError(str(exc)) from exc
            raise NoDeviceError(str(exc)) from exc

    # -- discovery / identity ---------------------------------------------

    async def list_devices(self) -> list[DeviceRef]:
        from pymobiledevice3 import usbmux

        raw = await usbmux.list_devices(usbmux_address=self._usbmux_address)
        return [
            DeviceRef(
                udid=d.serial,
                connection_type=_as_connection_type(getattr(d, "connection_type", "")),
                serial=d.serial,
            )
            for d in raw
        ]

    async def get_info(self, udid: Optional[str] = None) -> DeviceInfo:
        async with await self._lockdown(udid) as lockdown:
            values: dict[str, Any] = dict(lockdown.all_values or {})
            info = DeviceInfo(
                udid=lockdown.udid,
                name=values.get("DeviceName"),
                model=_model_name(values),
                product_type=values.get("ProductType"),
                device_class=values.get("DeviceClass"),
                ios_version=values.get("ProductVersion"),
                build_version=values.get("BuildVersion"),
                serial_number=values.get("SerialNumber"),
                imei=values.get("InternationalMobileEquipmentIdentity"),
                phone_number=values.get("PhoneNumber"),
                raw=values,
            )
            try:
                from pymobiledevice3.services.diagnostics import DiagnosticsService

                async with DiagnosticsService(lockdown) as diag:
                    battery = await diag.get_battery() or {}
                    info.battery_level = battery.get("BatteryCurrentCapacity")
                    info.battery_charging = _is_charging(battery)
                    diag_info = await diag.info("All") or {}
                    disk = diag_info.get("com.apple.disk_usage") or {}
                    if disk:
                        info.storage_total = disk.get("TotalDataCapacity") or disk.get("TotalDiskCapacity")
                        info.storage_free = disk.get("TotalDataAvailable") or disk.get("AvailableCapacity")
            except Exception:  # noqa: BLE001 - diagnostics is best-effort
                pass
            return info

    async def get_value(self, udid: Optional[str], key: str, domain: Optional[str] = None):
        async with await self._lockdown(udid) as lockdown:
            return await lockdown.get_value(domain=domain, key=key)

    # -- AFC ---------------------------------------------------------------

    async def _afc(self, udid: Optional[str]):
        from pymobiledevice3.services.afc import AfcService

        lockdown = await self._lockdown(udid)
        return lockdown, AfcService(lockdown)

    async def afc_listdir(self, udid: Optional[str], path: str) -> list[FileEntry]:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                base = path.rstrip("/") or "/"
                names = await afc.listdir(base or "/")
                entries: list[FileEntry] = []
                for name in names:
                    if name in (".", ".."):
                        continue
                    full = f"{base}/{name}" if base != "/" else f"/{name}"
                    try:
                        st = await afc.stat(full)
                    except Exception:  # noqa: BLE001
                        st = {}
                    entries.append(
                        FileEntry(
                            name=name,
                            path=full,
                            is_dir=st.get("st_ifmt") == "S_IFDIR",
                            size=int(st.get("st_size", 0) or 0),
                            modified=_to_epoch(st.get("st_mtime")),
                        )
                    )
                entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
                return entries
        except AfcError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AfcError(str(exc)) from exc
        finally:
            await lockdown.close()

    async def afc_stat(self, udid: Optional[str], path: str) -> FileEntry:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                st = await afc.stat(path)
                return FileEntry(
                    name=path.rstrip("/").rsplit("/", 1)[-1] or "/",
                    path=path,
                    is_dir=st.get("st_ifmt") == "S_IFDIR",
                    size=int(st.get("st_size", 0) or 0),
                    modified=_to_epoch(st.get("st_mtime")),
                )
        finally:
            await lockdown.close()

    async def afc_get(self, udid: Optional[str], remote: str) -> bytes:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                return await afc.get_file_contents(remote)
        except Exception as exc:  # noqa: BLE001
            raise AfcError(str(exc)) from exc
        finally:
            await lockdown.close()

    async def afc_put(self, udid: Optional[str], remote: str, data: bytes) -> None:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                await afc.set_file_contents(remote, data)
        except Exception as exc:  # noqa: BLE001
            raise AfcError(str(exc)) from exc
        finally:
            await lockdown.close()

    async def afc_pull(
        self, udid: Optional[str], remote: str, local: str,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        lockdown, afc = await self._afc(udid)
        _emit(progress, "pull", 0.0, f"{remote} -> {local}")
        try:
            async with afc:
                await afc.pull(remote, local, progress_bar=False)
            _emit(progress, "pull", 1.0, "done")
        except Exception as exc:  # noqa: BLE001
            raise AfcError(str(exc)) from exc
        finally:
            await lockdown.close()

    async def afc_push(
        self, udid: Optional[str], local: str, remote: str,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        lockdown, afc = await self._afc(udid)
        _emit(progress, "push", 0.0, f"{local} -> {remote}")
        try:
            async with afc:
                await afc.push(local, remote, progress_bar=False)
            _emit(progress, "push", 1.0, "done")
        except Exception as exc:  # noqa: BLE001
            raise AfcError(str(exc)) from exc
        finally:
            await lockdown.close()

    async def afc_rm(self, udid: Optional[str], path: str) -> None:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                await afc.rm(path, force=True)
        finally:
            await lockdown.close()

    async def afc_mkdir(self, udid: Optional[str], path: str) -> None:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                await afc.makedirs(path)
        finally:
            await lockdown.close()

    async def afc_rename(self, udid: Optional[str], src: str, dst: str) -> None:
        lockdown, afc = await self._afc(udid)
        try:
            async with afc:
                await afc.rename(src, dst)
        finally:
            await lockdown.close()

    # -- applications ------------------------------------------------------

    async def list_apps(self, udid: Optional[str], app_type: str = "Any") -> list[AppInfo]:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        async with await self._lockdown(udid) as lockdown:
            async with InstallationProxyService(lockdown) as proxy:
                apps = await proxy.get_apps(application_type=app_type)
        result: list[AppInfo] = []
        for bundle_id, meta in apps.items():
            result.append(
                AppInfo(
                    bundle_identifier=bundle_id,
                    name=meta.get("CFBundleDisplayName") or meta.get("CFBundleName"),
                    version=meta.get("CFBundleShortVersionString") or meta.get("CFBundleVersion"),
                    app_type=meta.get("ApplicationType"),
                    path=meta.get("Path"),
                    container=meta.get("Container"),
                    size=(meta.get("StaticDiskUsage") or 0) + (meta.get("DynamicDiskUsage") or 0) or None,
                    raw=meta,
                )
            )
        result.sort(key=lambda a: (a.name or a.bundle_identifier).lower())
        return result

    async def install_app(
        self, udid: Optional[str], ipa_path: str, developer: bool = False,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        def _handler(percent: Any, *_a: Any) -> None:
            frac = None
            if isinstance(percent, (int, float)):
                frac = float(percent) / 100.0 if percent > 1 else float(percent)
            _emit(progress, "install", frac, f"installing {Path(ipa_path).name}")

        try:
            async with await self._lockdown(udid) as lockdown:
                async with InstallationProxyService(lockdown) as proxy:
                    await proxy.install_from_local(
                        ipa_path, developer=developer, handler=_handler
                    )
        except Exception as exc:  # noqa: BLE001
            raise AppError(str(exc)) from exc

    async def uninstall_app(self, udid: Optional[str], bundle_identifier: str) -> None:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        try:
            async with await self._lockdown(udid) as lockdown:
                async with InstallationProxyService(lockdown) as proxy:
                    await proxy.uninstall(bundle_identifier)
        except Exception as exc:  # noqa: BLE001
            raise AppError(str(exc)) from exc

    # -- backup / restore --------------------------------------------------

    async def backup(
        self, udid: Optional[str], destination: str, full: bool = True,
        password: str = "", progress: Optional[ProgressCallback] = None,
    ) -> None:
        from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

        def _cb(info: Any) -> None:
            _emit(progress, "backup", None, str(info))

        Path(destination).mkdir(parents=True, exist_ok=True)
        try:
            async with await self._lockdown(udid) as lockdown:
                async with Mobilebackup2Service(lockdown) as mb2:
                    await mb2.backup(
                        full=full,
                        backup_directory=destination,
                        password=password or "",
                        progress_callback=_cb,
                    )
        except Exception as exc:  # noqa: BLE001
            raise BackupError(str(exc)) from exc

    async def restore(
        self, udid: Optional[str], source: str, password: str = "",
        reboot: bool = True, progress: Optional[ProgressCallback] = None,
    ) -> None:
        from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

        def _cb(info: Any) -> None:
            _emit(progress, "restore", None, str(info))

        try:
            async with await self._lockdown(udid) as lockdown:
                async with Mobilebackup2Service(lockdown) as mb2:
                    await mb2.restore(
                        backup_directory=source,
                        password=password or "",
                        reboot=reboot,
                        progress_callback=_cb,
                    )
        except Exception as exc:  # noqa: BLE001
            raise BackupError(str(exc)) from exc

    async def backup_info(self, udid: Optional[str], source: str) -> dict:
        from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

        async with await self._lockdown(udid) as lockdown:
            async with Mobilebackup2Service(lockdown) as mb2:
                text = await mb2.info(backup_directory=source)
        return {"text": text}

    # -- diagnostics / observability --------------------------------------

    async def diagnostics_info(self, udid: Optional[str]) -> dict:
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        async with await self._lockdown(udid) as lockdown:
            async with DiagnosticsService(lockdown) as diag:
                return {
                    "battery": await diag.get_battery(),
                    "info": await diag.info("All"),
                }

    async def screenshot(self, udid: Optional[str]) -> bytes:
        from pymobiledevice3.services.screenshot import ScreenshotService

        async with await self._lockdown(udid) as lockdown:
            async with ScreenshotService(lockdown) as shot:
                return await shot.take_screenshot()

    async def syslog(self, udid: Optional[str]) -> AsyncIterator[str]:
        from pymobiledevice3.services.syslog import SyslogService

        lockdown = await self._lockdown(udid)
        try:
            async with SyslogService(lockdown) as syslog:
                async for line in syslog.watch():
                    yield line if isinstance(line, str) else line.decode("utf-8", "replace")
        finally:
            await lockdown.close()

    # -- power / recovery --------------------------------------------------

    async def reboot(self, udid: Optional[str]) -> None:
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        async with await self._lockdown(udid) as lockdown:
            async with DiagnosticsService(lockdown) as diag:
                await diag.restart()

    async def enter_recovery(self, udid: Optional[str]) -> None:
        async with await self._lockdown(udid) as lockdown:
            await lockdown.enter_recovery()

    # -- firmware flashing (delegates to the tested CLI restore path) -----

    async def flash_firmware(
        self, ipsw_path: str, progress: Optional[ProgressCallback] = None,
        erase: bool = False,
    ) -> None:
        ipsw = Path(ipsw_path)
        if not ipsw.is_file():
            raise FirmwareError(f"IPSW not found: {ipsw_path}")

        cmd = [sys.executable, "-m", "pymobiledevice3", "restore", "update", "--ipsw", str(ipsw)]
        if erase:
            cmd.append("--erase")
        _emit(progress, "flash", 0.0, " ".join(cmd))

        def _run() -> None:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    _emit(progress, "flash", None, line)
            if proc.wait() != 0:
                raise FirmwareError(f"restore failed with exit code {proc.returncode}")

        try:
            await asyncio.to_thread(_run)
        except FirmwareError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FirmwareError(str(exc)) from exc
        _emit(progress, "flash", 1.0, "done")


# ---------------------------------------------------------------------------
# small pure helpers (module level so they are easy to unit-test)
# ---------------------------------------------------------------------------


def _model_name(values: dict[str, Any]) -> Optional[str]:
    """Best-effort marketing name from a lockdown value dict."""
    return (
        values.get("MarketingName")
        or values.get("ProductName")
        or values.get("ProductType")
    )


def _is_charging(battery: dict[str, Any]) -> Optional[bool]:
    state = battery.get("ExternalConnected")
    if state is None:
        return None
    charging = battery.get("IsCharging")
    if charging is None:
        return bool(state)
    return bool(charging)


def _to_epoch(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return int(value.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    return None
