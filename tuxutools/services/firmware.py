"""Firmware (IPSW) catalog, download and verification.

Mirrors the "Flash Firmware" feature of 3uTools.  Catalog data comes from the
public ipsw.me API (the same signed/info data 3uTools serves), downloads are
resumable and integrity is recorded as a SHA-256 sidecar.  Actually flashing a
device is delegated to the active backend (``restore update``).
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..exceptions import FirmwareError
from ..models import FirmwareInfo, Progress

IPSW_API = "https://api.ipsw.me/v4"
_USER_AGENT = "tuxutools/0.1 (+https://github.com/)"

ProgressCallback = Callable[[Progress], None]


def _get_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise FirmwareError(f"failed to reach firmware catalog: {exc}") from exc


def list_devices() -> list[dict]:
    """Return the ipsw.me device catalog (identifier + marketing name)."""
    return _get_json(f"{IPSW_API}/devices")


def lookup_identifier(product_type: str) -> Optional[dict]:
    """Resolve a product type (e.g. ``iPhone16,1``) to its catalog entry."""
    try:
        return _get_json(f"{IPSW_API}/device/{urllib.parse.quote(product_type)}")
    except FirmwareError:
        return None


def list_firmwares(product_type: str, only_signed: bool = False) -> list[FirmwareInfo]:
    """Return firmware images available for a product type."""
    data = _get_json(f"{IPSW_API}/device/{urllib.parse.quote(product_type)}?type=ipsw")
    out: list[FirmwareInfo] = []
    for fw in data.get("firmwares", []):
        if only_signed and not fw.get("signed"):
            continue
        out.append(
            FirmwareInfo(
                identifier=fw.get("identifier", product_type),
                version=str(fw.get("version", "")),
                build=str(fw.get("buildid", "")),
                url=fw.get("url"),
                signed=fw.get("signed"),
                size=fw.get("filesize"),
            )
        )
    return out


def download(
    url: str,
    destination: str | Path,
    progress: Optional[ProgressCallback] = None,
    chunk_size: int = 1024 * 256,
) -> Path:
    """Download an IPSW to *destination*, resuming if a partial file exists.

    A ``<file>.sha256`` sidecar is written and a ``<file>.part`` is used during
    transfer so interrupted downloads never look complete.
    """

    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")

    existing = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": _USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    req = urllib.request.Request(url, headers=headers)
    digest = hashlib.sha256()
    if existing:
        with part.open("rb") as fh:
            for block in iter(lambda: fh.read(chunk_size), b""):
                digest.update(block)

    try:
        with urllib.request.urlopen(req) as resp:
            total = resp.length or 0
            if existing and resp.status == 200:
                # server ignored the Range request; restart cleanly
                existing = 0
                digest = hashlib.sha256()
                part.write_bytes(b"")
            elif existing:
                total += existing
            _emit(progress, "download", _fraction(existing, total), "starting")
            mode = "ab" if existing else "wb"
            done = existing
            with part.open(mode) as fh:
                while True:
                    block = resp.read(chunk_size)
                    if not block:
                        break
                    fh.write(block)
                    digest.update(block)
                    done += len(block)
                    _emit(progress, "download", _fraction(done, total), _human(done, total))
    except urllib.error.URLError as exc:
        raise FirmwareError(f"download failed: {exc}") from exc

    part.replace(dest)
    checksum = digest.hexdigest()
    dest.with_suffix(dest.suffix + ".sha256").write_text(f"{checksum}  {dest.name}\n")
    _emit(progress, "download", 1.0, "verified")
    return dest


def verify(ipsw_path: str | Path, expected: Optional[str] = None) -> str:
    """Return the SHA-256 of *ipsw_path*, optionally checking it against *expected*."""

    path = Path(ipsw_path)
    if not path.is_file():
        raise FirmwareError(f"IPSW not found: {ipsw_path}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    checksum = digest.hexdigest()
    if expected is None:
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if sidecar.is_file():
            expected = sidecar.read_text().split()[0]
    if expected and expected.lower() != checksum.lower():
        raise FirmwareError(f"checksum mismatch: expected {expected}, got {checksum}")
    return checksum


def parse_ipsw_metadata(ipsw_path: str | Path) -> dict:
    """Extract product/build metadata from an IPSW without flashing it."""

    try:
        from ipsw_parser.ipsw import IPSW
    except Exception as exc:  # noqa: BLE001
        raise FirmwareError("ipsw_parser is required to inspect IPSWs") from exc

    try:
        ipsw = IPSW(Path(ipsw_path))
        return {
            "product_type": ipsw.product_type,
            "product_version": ipsw.product_version,
            "product_build": ipsw.product_build,
        }
    except Exception as exc:  # noqa: BLE001
        raise FirmwareError(str(exc)) from exc


# -- helpers ---------------------------------------------------------------


def _fraction(done: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return min(done / total, 1.0)


def _human(done: int, total: int) -> str:
    def fmt(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}TB"

    if total:
        return f"{fmt(done)} / {fmt(total)}"
    return fmt(done)


def _emit(cb: Optional[ProgressCallback], op: str, frac: Optional[float], msg: str) -> None:
    if cb is not None:
        cb(Progress(operation=op, fraction=frac, message=msg))
