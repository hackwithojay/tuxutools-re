import json

from tuxutools.cli import main


def test_cli_devices_json(capsys):
    code = main(["--mock", "--json", "devices"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["udid"].startswith("00008030")


def test_cli_info(capsys):
    code = main(["--mock", "info"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Mock iPhone" in out


def test_cli_ls(capsys):
    code = main(["--mock", "ls", "/"])
    assert code == 0
    assert "DCIM" in capsys.readouterr().out


def test_cli_firmware_verify(tmp_path, capsys):
    ipsw = tmp_path / "fw.ipsw"
    ipsw.write_bytes(b"firmware-bytes")
    code = main(["--mock", "firmware", "verify", str(ipsw)])
    assert code == 0
    assert "sha256" in capsys.readouterr().out


def test_cli_jailbreak_tools(capsys):
    code = main(["--mock", "jailbreak", "tools"])
    assert code == 0


def test_cli_backends_error_without_dep(monkeypatch):
    # Requesting the real backend with pymobiledevice3 hidden should fail cleanly.
    import tuxutools.backends.pmd3_backend as pmd3

    monkeypatch.setattr(pmd3, "pmd3_available", lambda: False)
    code = main(["--backend", "pymobiledevice3", "devices"])
    assert code in (1, 2)
