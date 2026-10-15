"""High-level feature services.

Each module implements one 3uTools capability group on top of the active
:class:`~tuxutools.backends.base.DeviceBackend`:

* :mod:`tuxutools.services.firmware`   - IPSW catalog, download, verify
* :mod:`tuxutools.services.jailbreak`  - palera1n/checkra1n integration
"""

from . import firmware, jailbreak

__all__ = ["firmware", "jailbreak"]
