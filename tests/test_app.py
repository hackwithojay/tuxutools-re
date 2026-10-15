from tuxutools.backends.mock_backend import FAKE_UDID


def test_devices_and_info(app):
    devices = app.devices()
    assert devices[0].udid == FAKE_UDID
    info = app.info()
    assert info.name == "Mock iPhone"


def test_file_operations(app):
    entries = app.list_dir("/")
    assert any(e.name == "DCIM" for e in entries)

    app.mkdir("/Scratch")
    app.put_file("/Scratch/a.txt", b"data")
    assert app.get_file("/Scratch/a.txt") == b"data"
    app.rename("/Scratch/a.txt", "/Scratch/b.txt")
    assert app.get_file("/Scratch/b.txt") == b"data"
    app.remove("/Scratch")


def test_apps_install_uninstall(app, tmp_path):
    ipa = tmp_path / "Foo.ipa"
    ipa.write_bytes(b"PK\x03\x04")
    app.install_ipa(str(ipa))
    assert any(a.bundle_identifier == "com.mock.foo" for a in app.apps())
    app.uninstall("com.mock.foo")
    assert not any(a.bundle_identifier == "com.mock.foo" for a in app.apps())


def test_backup_lifecycle(app, tmp_path):
    dest = app.backup(destination=str(tmp_path / "bk"))
    assert (tmp_path / "bk" / "Manifest.plist").is_file()


def test_list_local_backups(app):
    dest = app.backup()  # default destination under settings.backup_dir
    backups = app.list_local_backups()
    assert any(b.directory == dest for b in backups)


def test_export_photos(app, tmp_path):
    count = app.export_photos(str(tmp_path / "photos"))
    assert count == 2  # two files under DCIM/100APPLE
    assert (tmp_path / "photos" / "DCIM" / "100APPLE" / "IMG_0001.JPG").is_file()


def test_diagnostics_and_screenshot(app, tmp_path):
    diag = app.diagnostics()
    assert "battery" in diag
    shot = app.screenshot()
    out = tmp_path / "shot.png"
    out.write_bytes(shot)
    assert out.stat().st_size > 0
