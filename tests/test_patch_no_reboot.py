"""Tests for no-reboot firmware patch artifact helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_patch_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "patch_no_reboot.py"
    spec = importlib.util.spec_from_file_location("patch_no_reboot", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_code2_trailer_recalculates_checksum() -> None:
    tool = _load_patch_tool()
    code1 = bytes.fromhex("01000200")
    payload = bytes.fromhex("0300040005000600")
    trailer = (
        tool.BOOT_VALID_FLAG.to_bytes(4, "little")
        + (0x66B3).to_bytes(4, "little")
        + (0x8FE1).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + len(code1).to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
    )

    updated, note = tool.update_code2_trailer(code1, payload + trailer)

    updated_without_checksum = bytearray(updated)
    updated_without_checksum[-16:-12] = b"\x00\x00\x00\x00"
    expected = (
        tool.fw_chksum(code1) + tool.fw_chksum(updated_without_checksum)
    ) & 0xFFFF
    actual = int.from_bytes(updated[-16:-12], "little")

    assert actual == expected
    assert "0x8fe1" in note


def test_update_code2_trailer_rejects_missing_flag() -> None:
    tool = _load_patch_tool()
    bad_code2 = b"\x00" * tool.IOT_UPDATE_TRAILER_SIZE

    try:
        tool.update_code2_trailer(b"", bad_code2)
    except ValueError as exc:
        assert "trailer flag" in str(exc)
    else:
        raise AssertionError("expected invalid trailer flag to be rejected")
