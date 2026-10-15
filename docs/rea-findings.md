# Reverse-engineering findings (3uTools → TuxuTools)

This document records what was learned from the shipped Windows 3uTools
distribution and how each finding informs the Linux port. Evidence is labelled
per the REA methodology:

* **Observed** – directly read from a shipped artifact or REA/Ghidra output.
* **Inferred** – reasoned from observations, not directly proven.
* **Unknown** – not established by the evidence gathered so far.

All artifacts live in `../extracted/`; the REA evidence JSON files
(`analyze-idm_jb.json`, `decompile-jb.json`, `analyze-3utools.json`,
`7z-list.txt`) are in the parent `3utools-re/` directory.

---

## 1. Distribution

**Observed.** The installer is a Windows PE distribution; `payload.7z` (197 MiB,
LZMA2+BCJ) expands to 451 files / 589 MB. The top-level executables are:

| Executable         | Role (inferred)                          |
| ------------------ | ---------------------------------------- |
| `3uTools.exe`      | Qt5 main GUI + orchestrator (20 MB)      |
| `3uLauncher.exe`   | splash / updater launcher                |
| `3uViewer.exe`     | bundled file/media viewer                |
| `CrashReport.exe`  | crash reporter                           |
| `updater.exe`      | self-updater                             |
| `Uninstall.exe`    | uninstaller                              |
| `QtWebEngineProcess.exe` | Chromium helper for embedded web views |

**Observed.** Qt 5 (Core/Network/Qml/Quick/WebEngine/WebChannel/Svg/Print
Support), an ffmpeg 59 build, `heif.dll`, `sqlite.dll`, `sqlcipher.dll`,
`libcurl.dll`, `libssl-1_1.dll`. The Apple framework is bundled verbatim under
`itunesDll/` and `itunesFlashDll/` (CoreFoundation, CFNetwork, iTunes.dll,
AirTrafficHost, `asrp.dll`, …), with `iCloudDll/Anisette.exe` present.

**Inferred.** The GUI is Qt/C++; device work is delegated to feature DLLs (see
below) which sit on Apple's `MobileDevice`/iTunes support libraries.

---

## 2. Feature module map

**Observed.** The application ships a family of `idm_*` DLLs whose names map
one-to-one onto 3uTools feature areas:

| Module          | Feature area (inferred from name + role)      | TuxuTools home |
| --------------- | --------------------------------------------- | -------------- |
| `idm_info.dll`  | device information                            | `info`         |
| `idm_fm.dll`    | file manager (AFC)                            | `ls`/`pull`/`push` |
| `idm_app.dll`   | app management (install/uninstall)            | `apps`/`install`/`uninstall` |
| `idm_backup.dll`| backup / restore                              | `backup`/`restore` |
| `idm_media.dll` | media / photos                                | `export-photos` |
| `idm_sync.dll`  | sync                                          | (via backup/AFC) |
| `idm_datamgr.dll`| data manager / databases                     | (partial)      |
| `idm_jb*.dll`   | jailbreak, per iOS generation (6 / 7.1.x / 8.x / 9.0 / 8.13) | `jailbreak` |
| `idm_lang.dll`  | localisation                                  | n/a            |
| `idm_other.dll`, `idm_aia.dll` | miscellaneous / "app install assistant" | n/a |

Supporting native libraries (observed): `libidevicerestore.dll` (firmware
restore), `libphoto.dll`, `libacmr.dll`, `libcjpeg.dll`, `libhpdf.dll`,
`heif.dll` (media/codecs), `libidm_go.dll`, `libidmg.dll` (core).

**Inferred.** `idm_*` are the C++ feature backends; `3uTools.exe` is the Qt
front-end that loads them. This is the exact decomposition TuxuTools mirrors in
`backends/` + `services/`.

---

## 3. Jailbreak (deepest evidence collected)

**Observed – artifact identity.** `idm_jb.dll`, PE, x86, SHA-256
`3c7ea57016ee00d06a350c6f23a3f1ac7b1f090d1f24ac98951a9e6bf231e1e9`.
REA `binary_overview` (Evidence `ev_96d1fef6…`) reports 399 procedures, 553
strings, `.text` `0x10001000–0x1000de00` (52 736 bytes).

**Observed – `ios_jailbreak` pseudocode** (REA `procedure_pseudo_code`,
`decompile-jb.json`). Recovered facts from the decompiled function:

* Reads a version string and compares byte-wise against `"9.0…"` (the
  decompiler shows literal comparisons with `0x39 0x2e 0x30` = `'9' '.' '0'`),
  selecting a jailbreak generation by iOS version.
* Builds filesystem paths with the wide strings `files\jb90\` and
  `files\jb90.7z` (and elsewhere `files\jb6\` in the same module family).
* Uses `_time64` (staging/timestamp), `FILE`-based staging, and an archive
  extraction helper — consistent with unpacking a version-specific `.7z`
  payload next to the executable.
* Has a `__security_check_cookie` / `_invalid_parameter_noinfo_noreturn` MSVC
  runtime prologue — i.e. ordinary MSVC C++ code, not packed.

**Inferred.** 3uTools performs *offline, checkm8-class* jailbreaks by shipping
per-iOS-version payloads (`jb6`, `jb71x`, `jb8x`, `jb90`) and driving the device
through DFU/recovery. It is not a remote/online jailbreak service.

**Port decision.** TuxuTools does not re-implement the exploit. It integrates
the maintained Linux tools (`palera1n`, `checkra1n`, `gaster`) — which use the
same checkm8 bootrom exploit — and exposes the bundled `files/jb*.7z` payloads
when the extracted tree is present (`config.bundled_files_dir`,
`services/jailbreak.py:bundled_payloads`). Supported product types are listed in
`CHECKM8_PRODUCT_TYPES`.

---

## 4. Firmware / restore

**Observed.** `libidevicerestore.dll` ships with the app; `files/inf/`
contains USB driver installers (`InfInstallerx64.exe`), and `files/patchtools/`
ships 7-Zip binaries used to stage firmware.

**Inferred.** Firmware flashing is delegated to the open-source
`idevicerestore` engine plus Apple's TSS signing service.

**Port decision.** `services/firmware.py` fetches the same public firmware
catalog, downloads resumably with SHA-256 verification, and flashes via
`pymobiledevice3 restore update [--erase]` (a modern Linux restore engine).

---

## 5. What was *not* recovered

**Unknown.** The earlier attempt to run a full `list_documents` analysis over
the 20 MB `3uTools.exe` timed out after 40 minutes
(`analyze-3utools.json`, `provider_timeout`). Consequently the following remain
unresolved and should be analysed with focused, per-function Ghidra passes:

* the exact online-service endpoints used by `libcurl`/`idm_*`
  (e.g. activation, SHSH, app-store helpers);
* `idm_aia.dll` / `idm_813.dll` responsibilities;
* signature/DRM behaviour in `idm_app.dll`;
* the precise TSS/AP-ticket request construction (Apple's protocol, largely
  open, but not confirmed from these binaries).

These are bounded unknowns, not negative results: each needs its own
targeted query.

---

## 6. Reproduce the evidence

```bash
# module inventory
7z l payload.7z | grep -Ei 'idm_|\.exe$'

# module overview + one decompiled procedure
rea inspect && rea analyze extracted/idm_jb.dll
rea decompile extracted/idm_jb.dll ios_jailbreak
```

The committed JSON files in the parent directory are the raw REA Evidence the
summaries above cite.
