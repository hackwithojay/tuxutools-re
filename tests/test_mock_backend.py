from tuxutools.backends.mock_backend import MockBackend, FAKE_UDID
from tuxutools.exceptions import AfcError, AppError, NoDeviceError

from conftest import run


def test_list_devices(mock_backend):
    devices = run(mock_backend.list_devices())
    assert len(devices) == 1
    assert devices[0].udid == FAKE_UDID


def test_offline_lists_no_devices():
    offline = MockBackend(offline=True)
    assert run(offline.list_devices()) == []


def test_offline_get_info_raises():
    offline = MockBackend(offline=True)
    try:
        run(offline.get_info())
    except NoDeviceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected NoDeviceError")


def test_get_info(mock_backend):
    info = run(mock_backend.get_info())
    assert info.udid == FAKE_UDID
    assert info.ios_version == "18.0"
    assert info.battery_level == 87


def test_afc_listdir_sorted_with_dirs_first(mock_backend):
    entries = run(mock_backend.afc_listdir(None, "/"))
    names = [e.name for e in entries]
    assert names[0] == "Books"  # directories sort first
    assert "Downloads" in names


def test_afc_put_get_roundtrip(mock_backend):
    run(mock_backend.afc_put(None, "/Downloads/hello.txt", b"hi there"))
    assert run(mock_backend.afc_get(None, "/Downloads/hello.txt")) == b"hi there"


def test_afc_mkdir_rm(mock_backend):
    run(mock_backend.afc_mkdir(None, "/NewDir"))
    assert run(mock_backend.afc_stat(None, "/NewDir")).is_dir
    run(mock_backend.afc_rm(None, "/NewDir"))
    try:
        run(mock_backend.afc_stat(None, "/NewDir"))
    except AfcError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected AfcError")


def test_afc_rename(mock_backend):
    run(mock_backend.afc_rename(None, "/Downloads/notes.txt", "/Downloads/renamed.txt"))
    assert run(mock_backend.afc_get(None, "/Downloads/renamed.txt")) == b"hello from a mock device\n"


def test_afc_pull_to_disk(mock_backend, tmp_path):
    run(mock_backend.afc_pull(None, "/Downloads/notes.txt", str(tmp_path / "notes.txt")))
    assert (tmp_path / "notes.txt").read_bytes() == b"hello from a mock device\n"


def test_afc_push_from_disk(mock_backend, tmp_path):
    src = tmp_path / "upload.bin"
    src.write_bytes(b"payload")
    run(mock_backend.afc_push(None, str(src), "/Downloads/upload.bin"))
    assert run(mock_backend.afc_get(None, "/Downloads/upload.bin")) == b"payload"


def test_apps_and_install(mock_backend, tmp_path):
    apps = run(mock_backend.list_apps(None))
    assert any(a.bundle_identifier == "com.example.demo" for a in apps)

    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"PK\x03\x04 fake")
    run(mock_backend.install_app(None, str(ipa)))
    bundles = {a.bundle_identifier for a in run(mock_backend.list_apps(None))}
    assert "com.mock.myapp" in bundles


def test_uninstall_missing_raises(mock_backend):
    try:
        run(mock_backend.uninstall_app(None, "com.nope"))
    except AppError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected AppError")


def test_backup_and_restore(mock_backend, tmp_path):
    dest = tmp_path / "backup"
    run(mock_backend.backup(None, str(dest)))
    assert (dest / "Manifest.plist").is_file()
    run(mock_backend.restore(None, str(dest)))


def test_diagnostics_and_screenshot(mock_backend):
    assert run(mock_backend.diagnostics_info(None))["battery"]["BatteryCurrentCapacity"] == 87
    assert run(mock_backend.screenshot(None)).startswith(b"\x89PNG")
