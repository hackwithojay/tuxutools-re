"""Backend selection."""

from __future__ import annotations

from ..config import Settings
from ..exceptions import BackendUnavailableError
from .base import DeviceBackend, ProgressCallback

__all__ = ["DeviceBackend", "ProgressCallback", "create_backend", "available_backends"]


def available_backends() -> list[str]:
    from .pmd3_backend import pmd3_available

    names = ["mock"]
    if pmd3_available():
        names.insert(0, "pymobiledevice3")
    return names


def create_backend(settings: Settings | None = None) -> DeviceBackend:
    """Return a backend instance according to ``settings.backend``.

    ``auto`` prefers the real ``pymobiledevice3`` backend and falls back to the
    mock backend only when explicitly requested; an absent dependency is an
    error so a real install never silently pretends to talk to a device.
    """

    settings = settings or Settings()
    choice = (settings.backend or "auto").lower()

    if choice in ("mock", "fake", "virtual"):
        from .mock_backend import MockBackend

        return MockBackend()

    from .pmd3_backend import Pymobiledevice3Backend, pmd3_available

    if choice in ("auto", "pymobiledevice3", "pmd3", "real"):
        if not pmd3_available():
            raise BackendUnavailableError(
                "pymobiledevice3 backend requested but not installed. "
                "Install it or select the 'mock' backend with TUXUTOOLS_BACKEND=mock."
            )
        return Pymobiledevice3Backend(usbmux_address=settings.usbmux_address)

    raise BackendUnavailableError(f"unknown backend: {choice!r} (available: {available_backends()})")
