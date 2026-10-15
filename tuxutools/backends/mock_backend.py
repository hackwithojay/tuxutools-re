"""Deterministic in-memory backend.

Lets the CLI, GUI and test-suite run without an iOS device or the
``pymobiledevice3`` dependency.  A virtual filesystem, app list and backup
directory are exposed so every service path can be exercised in CI.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Optional

from ..exceptions import AfcError, AppError, BackupError, NoDeviceError
from ..models import (
    AppInfo,
    ConnectionType,
    DeviceInfo,
    DeviceRef,
    FileEntry,
    Progress,
)
from .base import DeviceBackend, ProgressCallback, _emit

FAKE_UDID = "00008030-001A2D4E0A88802E"


class _Node:
    def __init__(self, name: str, is_dir: bool, size: int = 0, children: Optional[dict] = None,
                 data: bytes = b"") -> None:
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.children = children or {}
        self.data = data
        self.mtime = int(time.time())


def _default_tree() -> _Node:
    def f(name: str, size: int, content: bytes = b"") -> _Node:
        return _Node(name, is_dir=False, size=size, data=content or (b"x" * min(size, 4096)))

    def d(name: str, children: dict) -> _Node:
        return _Node(name, is_dir=True, children=children)

    return d(
        "/",
        {
            "DCIM": d("DCIM", {"100APPLE": d("100APPLE", {"IMG_0001.JPG": f("IMG_0001.JPG", 2400000), "IMG_0002.HEIC": f("IMG_0002.HEIC", 1800000)})}),
            "PublicStaging": d("PublicStaging", {}),
            "Downloads": d("Downloads", {"notes.txt": f("notes.txt", 42, b"hello from a mock device\n")}),
            "Books": d("Books", {}),
            "Recordings": d("Recordings", {}),
        },
    )


class MockBackend(DeviceBackend):
    name = "mock"

    def __init__(self, devices: Optional[list[DeviceRef]] = None, offline: bool = False) -> None:
        self._offline = offline
        self._devices = devices or [
            DeviceRef(udid=FAKE_UDID, connection_type=ConnectionType.USB, serial=FAKE_UDID)
        ]
        self._tree = _default_tree()
        self._apps: dict[str, AppInfo] = {
            "com.apple.mobilesafari": AppInfo(
                bundle_identifier="com.apple.mobilesafari", name="Safari",
                version="18.0", app_type="System", path="/Applications/MobileSafari.app",
            ),
            "com.example.demo": AppInfo(
                bundle_identifier="com.example.demo", name="Demo App",
                version="1.2.3", app_type="User",
                path="/private/var/containers/Bundle/Application/DEMO/Demo.app",
            ),
        }

    # -- helpers -----------------------------------------------------------

    def _require_online(self) -> None:
        if self._offline or not self._devices:
            raise NoDeviceError("no mock device connected")

    def _resolve(self, path: str) -> _Node:
        parts = [p for p in path.split("/") if p and p != "."]
        node = self._tree
        for part in parts:
            if not node.is_dir or part not in node.children:
                raise AfcError(f"No such file or directory: {path}")
            node = node.children[part]
        return node

    def _parent(self, path: str) -> tuple[_Node, str]:
        parts = [p for p in path.split("/") if p and p != "."]
        if not parts:
            raise AfcError("cannot operate on root")
        name = parts[-1]
        node = self._tree
        for part in parts[:-1]:
            if part not in node.children or not node.children[part].is_dir:
                raise AfcError(f"No such directory: {path}")
            node = node.children[part]
        return node, name

    # -- discovery ---------------------------------------------------------

    async def list_devices(self) -> list[DeviceRef]:
        return [] if self._offline else list(self._devices)

    async def get_info(self, udid: Optional[str] = None) -> DeviceInfo:
        self._require_online()
        return DeviceInfo(
            udid=udid or self._devices[0].udid,
            name="Mock iPhone",
            model="iPhone 15 Pro",
            product_type="iPhone16,1",
            device_class="iPhone",
            ios_version="18.0",
            build_version="22A3354",
            serial_number="MOCK123456789",
            imei="000000000000000",
            battery_level=87,
            battery_charging=True,
            storage_total=256 * 1024**3,
            storage_free=142 * 1024**3,
            raw={"DeviceName": "Mock iPhone", "ProductVersion": "18.0"},
        )

    # -- AFC ---------------------------------------------------------------

    async def afc_listdir(self, udid: Optional[str], path: str) -> list[FileEntry]:
        self._require_online()
        node = self._resolve(path)
        if not node.is_dir:
            raise AfcError(f"Not a directory: {path}")
        base = path.rstrip("/")
        out = []
        for child in node.children.values():
            out.append(
                FileEntry(
                    name=child.name,
                    path=f"{base}/{child.name}" if base else f"/{child.name}",
                    is_dir=child.is_dir,
                    size=0 if child.is_dir else child.size,
                    modified=child.mtime,
                )
            )
        out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return out

    async def afc_stat(self, udid: Optional[str], path: str) -> FileEntry:
        self._require_online()
        node = self._resolve(path)
        return FileEntry(
            name=node.name, path=path, is_dir=node.is_dir,
            size=0 if node.is_dir else node.size, modified=node.mtime,
        )

    async def afc_get(self, udid: Optional[str], remote: str) -> bytes:
        self._require_online()
        node = self._resolve(remote)
        if node.is_dir:
            raise AfcError("is a directory")
        return node.data

    async def afc_put(self, udid: Optional[str], remote: str, data: bytes) -> None:
        self._require_online()
        parent, name = self._parent(remote)
        parent.children[name] = _Node(name, is_dir=False, size=len(data), data=data)

    async def afc_pull(self, udid: Optional[str], remote: str, local: str,
                       progress: Optional[ProgressCallback] = None) -> None:
        from pathlib import Path

        self._require_online()
        node = self._resolve(remote)
        _emit(progress, "pull", 0.5, f"{remote} -> {local}")
        dest = Path(local)
        if node.is_dir:
            dest.mkdir(parents=True, exist_ok=True)
            for child in node.children.values():
                (dest / child.name).write_bytes(child.data if not child.is_dir else b"")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(node.data)
        _emit(progress, "pull", 1.0, "done")

    async def afc_push(self, udid: Optional[str], local: str, remote: str,
                       progress: Optional[ProgressCallback] = None) -> None:
        from pathlib import Path

        self._require_online()
        src = Path(local)
        _emit(progress, "push", 0.5, f"{local} -> {remote}")
        data = src.read_bytes() if src.is_file() else b""
        parent, name = self._parent(remote)
        parent.children[name] = _Node(name, is_dir=src.is_dir(), size=len(data), data=data)
        _emit(progress, "push", 1.0, "done")

    async def afc_rm(self, udid: Optional[str], path: str) -> None:
        self._require_online()
        parent, name = self._parent(path)
        parent.children.pop(name, None)

    async def afc_mkdir(self, udid: Optional[str], path: str) -> None:
        self._require_online()
        parent, name = self._parent(path)
        parent.children[name] = _Node(name, is_dir=True)

    async def afc_rename(self, udid: Optional[str], src: str, dst: str) -> None:
        self._require_online()
        node = self._resolve(src)
        p_src, n_src = self._parent(src)
        p_dst, n_dst = self._parent(dst)
        p_src.children.pop(n_src, None)
        node.name = n_dst
        p_dst.children[n_dst] = node

    # -- apps --------------------------------------------------------------

    async def list_apps(self, udid: Optional[str], app_type: str = "Any") -> list[AppInfo]:
        self._require_online()
        apps = list(self._apps.values())
        if app_type and app_type != "Any":
            apps = [a for a in apps if a.app_type == app_type]
        return apps

    async def install_app(self, udid: Optional[str], ipa_path: str, developer: bool = False,
                          progress: Optional[ProgressCallback] = None) -> None:
        from pathlib import Path

        self._require_online()
        if not Path(ipa_path).is_file():
            raise AppError(f"IPA not found: {ipa_path}")
        _emit(progress, "install", 0.5, f"installing {Path(ipa_path).name}")
        name = Path(ipa_path).stem
        bid = f"com.mock.{name.lower()}"
        self._apps[bid] = AppInfo(bundle_identifier=bid, name=name, version="1.0", app_type="User")
        _emit(progress, "install", 1.0, "done")

    async def uninstall_app(self, udid: Optional[str], bundle_identifier: str) -> None:
        self._require_online()
        if bundle_identifier not in self._apps:
            raise AppError(f"not installed: {bundle_identifier}")
        del self._apps[bundle_identifier]

    # -- backup / restore --------------------------------------------------

    async def backup(self, udid: Optional[str], destination: str, full: bool = True,
                     password: str = "", progress: Optional[ProgressCallback] = None) -> None:
        import json
        from pathlib import Path

        self._require_online()
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        _emit(progress, "backup", 0.5, "writing")
        (dest / "Manifest.plist").write_text(json.dumps({"Mock": True, "full": full}))
        (dest / "Info.plist").write_text(json.dumps({"Product Version": "18.0", "Device Name": "Mock iPhone"}))
        _emit(progress, "backup", 1.0, "done")

    async def restore(self, udid: Optional[str], source: str, password: str = "",
                      reboot: bool = True, progress: Optional[ProgressCallback] = None) -> None:
        from pathlib import Path

        self._require_online()
        if not (Path(source) / "Manifest.plist").is_file():
            raise BackupError(f"not a backup directory: {source}")
        _emit(progress, "restore", 0.5, "restoring")
        _emit(progress, "restore", 1.0, "done")

    async def backup_info(self, udid: Optional[str], source: str) -> dict:
        import json
        from pathlib import Path

        info = Path(source) / "Info.plist"
        if info.is_file():
            return {"text": info.read_text()}
        return {"text": ""}

    # -- diagnostics -------------------------------------------------------

    async def diagnostics_info(self, udid: Optional[str]) -> dict:
        self._require_online()
        return {
            "battery": {"BatteryCurrentCapacity": 87, "ExternalConnected": True, "IsCharging": True},
            "info": {"com.apple.disk_usage": {"TotalDataCapacity": 256 * 1024**3, "TotalDataAvailable": 142 * 1024**3}},
        }

    async def screenshot(self, udid: Optional[str]) -> bytes:
        self._require_online()
        return b"\x89PNG\r\n\x1a\nMOCK"

    async def syslog(self, udid: Optional[str]) -> AsyncIterator[str]:
        self._require_online()
        for i in range(3):
            yield f"mock syslog line {i}"

    async def reboot(self, udid: Optional[str]) -> None:
        self._require_online()

    async def enter_recovery(self, udid: Optional[str]) -> None:
        self._require_online()

    async def flash_firmware(self, ipsw_path: str, progress: Optional[ProgressCallback] = None,
                             erase: bool = False) -> None:
        _emit(progress, "flash", 0.5, f"flashing {ipsw_path}")
        _emit(progress, "flash", 1.0, "done")
