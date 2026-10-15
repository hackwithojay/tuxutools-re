"""Exception hierarchy for the TuxuTools port."""


class TuxuToolsError(Exception):
    """Base class for all TuxuTools errors."""


class BackendUnavailableError(TuxuToolsError):
    """The selected device backend cannot be used (missing dependency, no daemon)."""


class NoDeviceError(TuxuToolsError):
    """No iOS device matched the requested selector."""


class DeviceNotPairedError(TuxuToolsError):
    """The device is connected but has not been trusted/paired yet."""


class DeviceLockedError(TuxuToolsError):
    """The device is locked and refuses the requested operation."""


class AfcError(TuxuToolsError):
    """A file-transfer (AFC) operation failed."""


class AppError(TuxuToolsError):
    """An application install/uninstall/query operation failed."""


class BackupError(TuxuToolsError):
    """A backup or restore operation failed."""


class FirmwareError(TuxuToolsError):
    """A firmware download, verification or flashing operation failed."""


class JailbreakError(TuxuToolsError):
    """A jailbreak related operation failed."""


class UnsupportedOperationError(TuxuToolsError):
    """The active backend does not implement the requested operation."""
