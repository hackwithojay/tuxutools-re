from pathlib import Path

import pytest

from tuxutools.exceptions import FirmwareError
from tuxutools.services import firmware as fw
from tuxutools.services import jailbreak as jb


def test_verify_matches_sidecar(tmp_path):
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"abc")
    digest = fw.verify(ipsw)
    # sidecar now written; verifying again should pass without explicit expected
    assert fw.verify(ipsw) == digest


def test_verify_mismatch_raises(tmp_path):
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"abc")
    with pytest.raises(FirmwareError):
        fw.verify(ipsw, expected="0" * 64)


def test_verify_missing_raises(tmp_path):
    with pytest.raises(FirmwareError):
        fw.verify(tmp_path / "nope.ipsw")


def test_human_and_fraction_helpers():
    assert fw._fraction(50, 100) == 0.5
    assert fw._fraction(1, 0) is None
    assert fw._human(0, 0) == "0.0B"


def test_supports_checkm8():
    assert jb.supports_checkm8("iPhone10,6")
    assert not jb.supports_checkm8("iPhone14,2")
    assert not jb.supports_checkm8(None)


def test_detect_tools_returns_known_keys():
    tools = jb.detect_tools()
    assert set(tools) >= {"palera1n", "checkra1n", "gaster"}


def test_run_palera1n_missing_tool(monkeypatch):
    monkeypatch.setattr(jb, "_require_tool", lambda name: (_ for _ in ()).throw(jb.JailbreakError("nope")))
    with pytest.raises(jb.JailbreakError):
        jb.run_palera1n()
