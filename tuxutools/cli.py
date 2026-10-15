"""``tuxutools`` command line interface.

A thin, scriptable front-end over :class:`tuxutools.app.TuxuTools`.  Every
subcommand maps to a 3uTools feature area; ``--json`` makes output machine
readable and ``--mock`` selects the hardware-free backend.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from . import __version__
from .app import TuxuTools
from .config import Settings
from .exceptions import TuxuToolsError
from .models import Progress


def _human_bytes(n: Optional[int]) -> str:
    if not n:
        return "-"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


class _ProgressPrinter:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._last = ""

    def __call__(self, progress: Progress) -> None:
        if self.quiet:
            return
        frac = f"{progress.fraction * 100:5.1f}%" if progress.fraction is not None else "  ...  "
        line = f"[{progress.operation}] {frac} {progress.message}"
        if line != self._last:
            sys.stderr.write(line[:160] + "\n")
            sys.stderr.flush()
            self._last = line


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tuxutools",
        description="Linux reimplementation of 3uTools (iOS device manager).",
    )
    parser.add_argument("--version", action="version", version=f"tuxutools {__version__}")
    parser.add_argument("--udid", help="target device UDID (default: first connected)")
    parser.add_argument("--backend", choices=["auto", "pymobiledevice3", "mock"],
                        help="device backend to use")
    parser.add_argument("--mock", action="store_true", help="shortcut for --backend mock")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list connected devices")

    p = sub.add_parser("info", help="show device information")
    p.add_argument("udid", nargs="?")

    p = sub.add_parser("ls", help="list a directory on the device")
    p.add_argument("path", nargs="?", default="/")

    p = sub.add_parser("pull", help="copy a file/dir from device to host")
    p.add_argument("remote")
    p.add_argument("local")

    p = sub.add_parser("push", help="copy a file/dir from host to device")
    p.add_argument("local")
    p.add_argument("remote")

    p = sub.add_parser("mkdir", help="create a directory on the device")
    p.add_argument("path")

    p = sub.add_parser("rm", help="remove a path on the device")
    p.add_argument("path")

    p = sub.add_parser("rename", help="rename a path on the device")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("apps", help="list installed applications")
    p.add_argument("--type", default="Any", choices=["Any", "User", "System"])

    p = sub.add_parser("install", help="install an IPA")
    p.add_argument("ipa")
    p.add_argument("--developer", action="store_true")

    p = sub.add_parser("uninstall", help="uninstall an app by bundle id")
    p.add_argument("bundle_id")

    p = sub.add_parser("backup", help="back up the device")
    p.add_argument("--dest")
    p.add_argument("--password", default="")
    p.add_argument("--full", action="store_true", default=True)

    p = sub.add_parser("restore", help="restore a backup")
    p.add_argument("source")
    p.add_argument("--password", default="")
    p.add_argument("--no-reboot", action="store_true")

    sub.add_parser("backups", help="list local backups")

    p = sub.add_parser("backup-info", help="show info about a backup")
    p.add_argument("source")

    sub.add_parser("diagnostics", help="battery/storage diagnostics")

    p = sub.add_parser("screenshot", help="capture a screenshot")
    p.add_argument("output", nargs="?", default="screenshot.png")

    p = sub.add_parser("syslog", help="stream device syslog")
    p.add_argument("--lines", type=int, default=20)

    sub.add_parser("reboot", help="reboot the device")
    sub.add_parser("recovery", help="reboot into recovery mode")

    p = sub.add_parser("export-photos", help="copy the camera roll to a directory")
    p.add_argument("destination")
    p.add_argument("--remote", default="/DCIM")

    p = sub.add_parser("import-photo", help="upload a photo to the device")
    p.add_argument("file")

    fw = sub.add_parser("firmware", help="firmware (IPSW) operations").add_subparsers(
        dest="fw_command", required=True
    )
    fwl = fw.add_parser("list", help="list firmwares for a product type")
    fwl.add_argument("product_type", help="e.g. iPhone16,1")
    fwl.add_argument("--signed", action="store_true")
    fwd = fw.add_parser("download", help="download an IPSW")
    fwd.add_argument("url")
    fwd.add_argument("--dest")
    fwv = fw.add_parser("verify", help="verify an IPSW checksum")
    fwv.add_argument("ipsw")
    fwv.add_argument("--sha256")
    fwf = fw.add_parser("flash", help="flash an IPSW onto the device")
    fwf.add_argument("ipsw")
    fwf.add_argument("--erase", action="store_true")

    jb = sub.add_parser("jailbreak", help="jailbreak operations").add_subparsers(
        dest="jb_command", required=True
    )
    jb.add_parser("tools", help="detect jailbreak tools")
    jb.add_parser("payloads", help="list bundled 3uTools jailbreak payloads")
    jbr = jb.add_parser("run", help="run a jailbreak tool")
    jbr.add_argument("--method", choices=["palera1n", "checkra1n"], default="palera1n")
    jbr.add_argument("--rootful", action="store_true")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    if args.backend:
        settings.backend = args.backend
    if args.mock:
        settings.backend = "mock"

    try:
        app = TuxuTools(settings=settings)
    except TuxuToolsError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    udid = args.udid
    progress = _ProgressPrinter(quiet=args.quiet or args.json)
    out = sys.stdout

    def emit(value: Any, text: str) -> None:
        if args.json:
            out.write(json.dumps(value, indent=2, default=str) + "\n")
        else:
            out.write(text + "\n")

    try:
        return _dispatch(app, args, udid, progress, emit)
    except TuxuToolsError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    finally:
        app.close()


def _dispatch(app: TuxuTools, args, udid, progress, emit) -> int:
    cmd = args.command

    if cmd == "devices":
        devices = app.devices()
        emit([d.to_dict() for d in devices],
             "\n".join(f"{d.udid}  {d.connection_type.value}" for d in devices) or "no devices")
        return 0

    if cmd == "info":
        info = app.info(args.udid or udid)
        emit(info.to_dict(), _format_info(info))
        return 0

    if cmd == "ls":
        entries = app.list_dir(args.path, udid=udid)
        emit([e.to_dict() for e in entries], _format_ls(entries))
        return 0

    if cmd == "pull":
        app.pull(args.remote, args.local, udid=udid, progress=progress)
        return 0

    if cmd == "push":
        app.push(args.local, args.remote, udid=udid, progress=progress)
        return 0

    if cmd == "mkdir":
        app.mkdir(args.path, udid=udid)
        return 0

    if cmd == "rm":
        app.remove(args.path, udid=udid)
        return 0

    if cmd == "rename":
        app.rename(args.src, args.dst, udid=udid)
        return 0

    if cmd == "apps":
        apps = app.apps(args.type, udid=udid)
        emit([a.to_dict() for a in apps], _format_apps(apps))
        return 0

    if cmd == "install":
        app.install_ipa(args.ipa, udid=udid, developer=args.developer, progress=progress)
        emit({"installed": args.ipa}, f"installed {args.ipa}")
        return 0

    if cmd == "uninstall":
        app.uninstall(args.bundle_id, udid=udid)
        emit({"uninstalled": args.bundle_id}, f"uninstalled {args.bundle_id}")
        return 0

    if cmd == "backup":
        dest = app.backup(udid=udid, destination=args.dest, password=args.password, progress=progress)
        emit({"backup": dest}, f"backup written to {dest}")
        return 0

    if cmd == "restore":
        app.restore(args.source, udid=udid, password=args.password,
                    reboot=not args.no_reboot, progress=progress)
        emit({"restored": args.source}, f"restored from {args.source}")
        return 0

    if cmd == "backups":
        backups = app.list_local_backups()
        emit([b.to_dict() for b in backups],
             "\n".join(f"{b.udid}  {b.date}  {b.product_version or '?'}  {b.directory}" for b in backups)
             or "no local backups")
        return 0

    if cmd == "backup-info":
        info = app.backup_info(args.source, udid=udid)
        emit(info, info.get("text", ""))
        return 0

    if cmd == "diagnostics":
        data = app.diagnostics(udid=udid)
        emit(data, json.dumps(data, indent=2, default=str))
        return 0

    if cmd == "screenshot":
        png = app.screenshot(udid=udid)
        with open(args.output, "wb") as fh:
            fh.write(png)
        emit({"screenshot": args.output, "bytes": len(png)}, f"saved {args.output} ({len(png)} bytes)")
        return 0

    if cmd == "syslog":
        import asyncio

        lines: list[str] = []

        async def _collect() -> None:
            count = 0
            async for line in app.backend.syslog(udid):
                lines.append(line)
                count += 1
                if count >= args.lines:
                    break

        asyncio.run(_collect())
        emit(lines, "\n".join(lines))
        return 0

    if cmd == "reboot":
        app.reboot(udid=udid)
        return 0

    if cmd == "recovery":
        app.enter_recovery(udid=udid)
        return 0

    if cmd == "export-photos":
        count = app.export_photos(args.destination, udid=udid, remote=args.remote, progress=progress)
        emit({"exported": count}, f"exported {count} files to {args.destination}")
        return 0

    if cmd == "import-photo":
        app.import_photo(args.file, udid=udid)
        emit({"imported": args.file}, f"imported {args.file}")
        return 0

    if cmd == "firmware":
        return _dispatch_firmware(app, args, progress, emit)

    if cmd == "jailbreak":
        return _dispatch_jailbreak(app, args, progress, emit)

    emit({}, f"unknown command: {cmd}")
    return 1


def _dispatch_firmware(app: TuxuTools, args, progress, emit) -> int:
    if args.fw_command == "list":
        fws = app.list_firmwares(args.product_type, only_signed=args.signed)
        emit([f.to_dict() for f in fws], _format_firmwares(fws))
        return 0
    if args.fw_command == "download":
        path = app.download_firmware(args.url, args.dest, progress=progress)
        emit({"downloaded": str(path)}, f"downloaded {path}")
        return 0
    if args.fw_command == "verify":
        digest = app.verify_firmware(args.ipsw, args.sha256)
        emit({"sha256": digest}, f"sha256 {digest}")
        return 0
    if args.fw_command == "flash":
        app.flash_firmware(args.ipsw, erase=args.erase, progress=progress)
        emit({"flashed": args.ipsw}, f"flashed {args.ipsw}")
        return 0
    return 1


def _dispatch_jailbreak(app: TuxuTools, args, progress, emit) -> int:
    if args.jb_command == "tools":
        tools = app.jailbreak_tools()
        data = {name: status.to_dict() for name, status in tools.items()}
        text = "\n".join(f"{name}: {status.path or 'not found'}" for name, status in tools.items())
        emit(data, text)
        return 0
    if args.jb_command == "payloads":
        payloads = [str(p) for p in app.jailbreak_payloads()]
        emit(payloads, "\n".join(payloads) or "no bundled payloads found")
        return 0
    if args.jb_command == "run":
        app.jailbreak(method=args.method, rootless=not args.rootful, progress=progress)
        emit({"jailbreak": args.method}, f"jailbreak via {args.method} finished")
        return 0
    return 1


# -- text formatters -------------------------------------------------------


def _format_info(info) -> str:
    rows = [
        ("Name", info.name),
        ("Model", info.model),
        ("Product type", info.product_type),
        ("iOS", f"{info.ios_version or '?'} ({info.build_version or '?'})"),
        ("Serial", info.serial_number),
        ("UDID", info.udid),
        ("IMEI", info.imei),
        ("Battery", f"{info.battery_level}%" + (" (charging)" if info.battery_charging else "") if info.battery_level is not None else "-"),
        ("Storage", f"{_human_bytes(info.storage_free)} free / {_human_bytes(info.storage_total)}"),
    ]
    return "\n".join(f"{k:14}: {v if v is not None else '-'}" for k, v in rows)


def _format_ls(entries) -> str:
    lines = []
    for e in entries:
        kind = "d" if e.is_dir else "-"
        lines.append(f"{kind} {_human_bytes(e.size):>10}  {e.name}")
    return "\n".join(lines) or "(empty)"


def _format_apps(apps) -> str:
    lines = []
    for a in apps:
        lines.append(f"{a.bundle_identifier:45} {a.version or '?':10} {a.name or ''}")
    return "\n".join(lines)


def _format_firmwares(fws) -> str:
    lines = []
    for f in fws:
        lines.append(
            f"{f.version:10} build {f.build:12} {'signed' if f.signed else 'unsigned':9} {_human_bytes(f.size)}"
        )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
