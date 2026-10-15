"""Jailbreak support.

The REA investigation of ``idm_jb.dll`` recovered the ``ios_jailbreak``
procedure and showed 3uTools driving checkm8-class jailbreaks from bundled
payloads (``files\\jb90\\`` / ``files\\jb90.7z``).  On Linux the equivalent,
maintained tooling is:
  * ``palera1n``   - checkm8 devices (A11 and below), rootful/rootless
  * ``checkra1n``  - checkm8 devices
  * ``gaster``     - DFU payload loader used by palera1n/checkra1n

This module detects those tools and the bundled payloads, reports which
methods a device supports, and runs the selected tool.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..config import Settings
from ..exceptions import JailbreakError
from ..models import Progress

ProgressCallback = Callable[[Progress], None]

#: Product types that use the checkm8 bootrom exploit (A11 / A7-A11 era).
CHECKM8_PRODUCT_TYPES = {
    "iPhone8,1", "iPhone8,2", "iPhone8,4", "iPhone9,1", "iPhone9,3",
    "iPhone10,1", "iPhone10,3", "iPhone10,2", "iPhone10,4", "iPhone10,6",
    "iPad6,11", "iPad6,12", "iPad7,1", "iPad7,2", "iPad7,3", "iPad7,4",
    "iPad7,5", "iPad7,6", "iPad7,11", "iPad7,12", "iPod9,1",
}

TOOLS = {
    "palera1n": ["palera1n", "palera1n-linux"],
    "checkra1n": ["checkra1n"],
    "gaster": ["gaster"],
    "irecovery": ["irecovery"],
}


@dataclass
class ToolStatus:
    name: str
    path: Optional[str]

    @property
    def available(self) -> bool:
        return self.path is not None

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.path, "available": self.available}


def detect_tools() -> dict[str, ToolStatus]:
    found: dict[str, ToolStatus] = {}
    for name, candidates in TOOLS.items():
        path = None
        for cand in candidates:
            located = shutil.which(cand)
            if located:
                path = located
                break
        found[name] = ToolStatus(name=name, path=path)
    return found


def bundled_payloads(settings: Optional[Settings] = None) -> list[Path]:
    """Return the 3uTools jailbreak payloads found in the extracted tree."""

    from ..config import bundled_files_dir

    base = bundled_files_dir()
    if base is None:
        return []
    payloads: list[Path] = []
    for pattern in ("jb*.7z", "jb*.zip", "jb*"):
        for path in sorted(base.glob(pattern)):
            if path not in payloads:
                payloads.append(path)
    return payloads


def supports_checkm8(product_type: Optional[str]) -> bool:
    return bool(product_type) and product_type in CHECKM8_PRODUCT_TYPES


def _require_tool(name: str) -> str:
    status = detect_tools().get(name)
    if status is None or not status.path:
        raise JailbreakError(
            f"{name} not found on PATH. Install it (see https://palera1n.com) "
            f"or place it in {Path.home() / '.local/bin'}."
        )
    return status.path


def _emit(cb: Optional[ProgressCallback], op: str, frac: Optional[float], msg: str) -> None:
    if cb is not None:
        cb(Progress(operation=op, fraction=frac, message=msg))


def run_palera1n(
    *,
    rootless: bool = True,
    setup_partitions: bool = False,
    verbose: bool = False,
    extra_args: Optional[list[str]] = None,
    progress: Optional[ProgressCallback] = None,
) -> int:
    """Run ``palera1n`` against a device already in DFU/recovery mode."""

    binary = _require_tool("palera1n")
    cmd = [binary]
    cmd += ["-l"] if rootless else ["-f"]
    if setup_partitions:
        cmd.append("-c")
    if verbose:
        cmd.append("-v")
    cmd += extra_args or []
    return _run(cmd, "palera1n", progress)


def run_checkra1n(
    *, cli: bool = True, extra_args: Optional[list[str]] = None,
    progress: Optional[ProgressCallback] = None,
) -> int:
    """Run ``checkra1n`` against a device already in DFU mode."""

    binary = _require_tool("checkra1n")
    cmd = [binary] + (["-c"] if cli else [])
    cmd += extra_args or []
    return _run(cmd, "checkra1n", progress)


def _run(cmd: list[str], label: str, progress: Optional[ProgressCallback]) -> int:
    _emit(progress, "jailbreak", 0.0, " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line:
                _emit(progress, "jailbreak", None, line)
        code = proc.wait()
    except FileNotFoundError as exc:
        raise JailbreakError(str(exc)) from exc
    if code != 0:
        raise JailbreakError(f"{label} exited with code {code}")
    _emit(progress, "jailbreak", 1.0, "done")
    return code
