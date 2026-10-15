"""TuxuTools - a Linux reimplementation of the 3uTools iOS device manager.

The project is a clean-room port guided by a static reverse-engineering pass
(REA/Ghidra) over the original Windows 3uTools distribution.  It speaks the
same Apple protocols (lockdown, AFC, installation_proxy, mobilebackup2,
diagnostics, recovery/restore) through ``pymobiledevice3``.
"""

from __future__ import annotations

__all__ = ["TuxuTools", "__version__"]

__version__ = "0.1.0"


def __getattr__(name: str):  # lazy import so ``import tuxutools`` stays cheap
    if name == "TuxuTools":
        from .app import TuxuTools

        return TuxuTools
    raise AttributeError(name)
