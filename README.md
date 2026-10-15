# TuxuTools

A Linux reimplementation of [3uTools](https://www.3u.com/), the iOS device
manager. It is a clean-room port guided by a static reverse-engineering pass
over the original Windows distribution (see
[`docs/rea-findings.md`](docs/rea-findings.md)).

TuxuTools speaks the same Apple protocols the original app used through
Apple's `MobileDevice` framework — **lockdown, AFC, installation_proxy,
mobilebackup2, diagnostics, screenshots, syslog, recovery/restore** — using
[`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3), the
maintained pure-Python implementation of the libimobiledevice stack.

## Features

| 3uTools area        | TuxuTools implementation                                              |
| ------------------- | --------------------------------------------------------------------- |
| Device info         | lockdown + diagnostics (model, iOS, battery, storage, IMEI)           |
| File browser        | AFC (`ls`, pull/push, mkdir, rm, rename)                              |
| App management      | installation_proxy (`list`, `install <ipa>`, `uninstall`)            |
| Backup & restore    | mobilebackup2 (`backup`, `restore`, list local backups)              |
| Media & photos      | DCIM export/import over AFC                                           |
| Firmware flashing   | IPSW catalog (ipsw.me), resumable download + SHA-256, `restore update`|
| Jailbreak           | palera1n / checkra1n integration + bundled-payload discovery          |
| Diagnostics         | battery/storage, screenshots, syslog streaming                        |

## Install

```bash
cd port
python3 -m venv .venv
.venv/bin/pip install -e .            # core (pymobiledevice3)
.venv/bin/pip install -e '.[gui]'     # optional PySide6 GUI
```

On Debian/Ubuntu the USB stack also needs the udev rules so non-root users can
access devices:

```bash
sudo apt install libimobiledevice-utils usbmuxd   # provides usbmuxd + udev rules
```

`pymobiledevice3` talks to USB directly, but installing `usbmuxd` lets multiple
apps share a device and provides the `usbmuxd` socket.

## Usage

### CLI

```bash
tuxutools devices
tuxutools info
tuxutools ls /
tuxutools pull /DCIM/100APPLE/IMG_0001.JPG ./photo.jpg
tuxutools apps --type User
tuxutools install ~/Downloads/MyApp.ipa
tuxutools backup
tuxutools backups
tuxutools restore ~/.local/share/tuxutools/backups/<udid>
tuxutools firmware list iPhone16,1 --signed
tuxutools firmware download https://.../iPhone.ipsw
tuxutools firmware flash ~/iPhone.ipsw --erase
tuxutools jailbreak tools
tuxutools jailbreak run --method palera1n
```

Add `--json` for machine-readable output or `--mock` to use the built-in
virtual device (no hardware or `pymobiledevice3` required):

```bash
tuxutools --mock devices
tuxutools --mock ls /
```

### GUI

```bash
tuxutools-gui            # or: python -m tuxutools.gui.app
tuxutools-gui --mock     # explore the UI without a device
```

Tabs: **Info · Files · Applications · Backup · Firmware · Jailbreak**.

To add a launcher to your application menu:

```bash
bash packaging/install-desktop.sh
```

`packaging/tuxutools.desktop` is path-agnostic (`Exec=tuxutools-gui`, resolved
via `$PATH`); the script resolves the real interpreter of your install and
writes the absolute path into `~/.local/share/applications/tuxutools.desktop`.

## Architecture

```
tuxutools/
  app.py                 synchronous facade (used by CLI + GUI)
  models.py              plain dataclasses (JSON-serialisable)
  config.py              XDG paths, settings, bundled-payload discovery
  exceptions.py          error hierarchy
  backends/
    base.py              DeviceBackend ABC (async)
    pmd3_backend.py      pymobiledevice3 implementation  (real devices)
    mock_backend.py      in-memory implementation        (tests / no hardware)
  services/
    firmware.py          IPSW catalog / download / verify
    jailbreak.py         palera1n / checkra1n / payload discovery
  cli.py                 argparse CLI
  gui/app.py             PySide6 GUI
```

The backend boundary means the whole stack can be exercised without an iOS
device (`--mock`), and a future backend (e.g. shelling out to
`libimobiledevice` CLI tools or a C++ rewrite) can be dropped in without
touching the services, CLI or GUI.

## Testing

```bash
cd port
python -m pytest -q
```

The suite runs entirely against the mock backend plus pure-unit tests for the
firmware and jailbreak services.

## Status & limitations

* Static/behavioural evidence comes from the reverse-engineering pass; exact
  parity with every 3uTools screen is not claimed.
* `flash_firmware` delegates to `pymobiledevice3 restore update` (the Linux
  equivalent of the original's `libidevicerestore` path).
* Jailbreak runs the maintained `palera1n`/`checkra1n` tools; it does not
  re-implement the checkm8 exploit payloads.
* Requires a real device to validate device paths end-to-end.

## License

GPL-3.0-or-later (matching the upstream tooling this depends on).
