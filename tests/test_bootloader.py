"""Tests for the ATBM6441 bootloader protocol module."""

from __future__ import annotations

import io
import struct
from unittest.mock import MagicMock, patch

import pytest

from atbm6441_cli.protocol.bootloader import (
    AT_GMR,
    AT_GET_SDK_VER,
    AT_REBOOT,
    AT_SEND,
    AT_START,
    AT_VENVER,
    AT_WIFI_GET_FWINFO,
    BootloaderProtocol,
    BootloaderResponse,
    FLASH_MEMORY_BASE,
    FirmwareSpec,
    BOOTLOADER_ADDR,
    BOOTLOADER_MAX_SIZE,
    CODE1_ADDR,
    CODE2_ADDR,
    KEY1_ADDR,
    KEY2_ADDR,
    MARKER_BOOTLOADER_MODE,
    MARKER_DOWNLOAD_FAIL,
    MARKER_DOWNLOAD_SUCCESS,
    MARKER_OK,
    MARKER_ROM_CODE_MODE,
    _parse_hex_memory_response,
    _parse_response,
)


# ── _parse_response tests ─────────────────────────────────────────────────


class TestParseResponse:
    """Test BootloaderResponse parsing."""

    def test_parse_bootloader_mode(self) -> None:
        raw = b"[ bootloader mode ]\r\n"
        resp = _parse_response(raw)
        assert resp.is_bootloader_mode is True
        assert resp.is_rom_code_mode is False
        assert resp.is_ok is False

    def test_parse_rom_code_mode(self) -> None:
        raw = b"[ rom code mode ]\r\n"
        resp = _parse_response(raw)
        assert resp.is_rom_code_mode is True
        assert resp.is_bootloader_mode is False

    def test_parse_download_success(self) -> None:
        raw = b"<<<   download SUCCESS   >>>\r\n"
        resp = _parse_response(raw)
        assert resp.is_download_success is True
        assert resp.is_download_fail is False

    def test_parse_download_fail(self) -> None:
        raw = b"download fail,please check boot download mode\r\n"
        resp = _parse_response(raw)
        assert resp.is_download_fail is True
        assert resp.is_download_success is False

    def test_parse_ok(self) -> None:
        raw = b"OK\r\n"
        resp = _parse_response(raw)
        assert resp.is_ok is True

    def test_parse_error(self) -> None:
        raw = b"ERROR: Invalid firmware filename\r\n"
        resp = _parse_response(raw)
        assert resp.is_error is True

    def test_parse_text(self) -> None:
        raw = b"[ bootloader mode ]\r\n"
        resp = _parse_response(raw)
        assert "bootloader mode" in resp.text

    def test_parse_empty(self) -> None:
        raw = b""
        resp = _parse_response(raw)
        assert resp.raw == b""
        assert resp.text == ""

    def test_parse_bootloader_memory_dump(self) -> None:
        raw = (
            b"Memory at 00400000:\r\n"
            b"  00400000: DEADBEEF 01020304\r\n"
            b"+OK"
        )
        parsed = _parse_hex_memory_response(raw, 8, base_address=FLASH_MEMORY_BASE)
        assert parsed == bytes.fromhex("EFBEADDE04030201")

    def test_parse_bootloader_relative_memory_dump(self) -> None:
        raw = (
            b">rmem 800800\r\n"
            b"Memory at 00800800:\r\n\r\n"
            b"00000000: F12EED3A 14BD4473 0268CFC3 C9BB5195\r\n"
            b">"
        )
        parsed = _parse_hex_memory_response(raw, 16, base_address=0x00800800)
        assert parsed == bytes.fromhex("3AED2EF17344BD14C3CF68029551BBC9")


# ── FirmwareSpec tests ───────────────────────────────────────────────────


class TestFirmwareSpec:
    """Test FirmwareSpec dataclass."""

    def test_default_values(self) -> None:
        spec = FirmwareSpec()
        assert spec.key1_addr == KEY1_ADDR
        assert spec.key2_addr == KEY2_ADDR
        assert spec.bootloader is None
        assert spec.code1 is None
        assert spec.code2 is None

    def test_custom_addresses(self) -> None:
        spec = FirmwareSpec(key1_addr=0x1000, key2_addr=0x2000)
        assert spec.key1_addr == 0x1000
        assert spec.key2_addr == 0x2000


# ── BootloaderProtocol tests ─────────────────────────────────────────────


class TestBootloaderProtocol:
    """Test BootloaderProtocol methods."""

    @pytest.fixture
    def mock_serial(self) -> MagicMock:
        """Create a mock SerialManager."""
        mock = MagicMock()
        mock.is_open = True
        return mock

    def test_enter_bootloader_success(self, mock_serial: MagicMock) -> None:
        mock_serial.read.return_value = b"[ bootloader mode ]\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.enter_bootloader()
        assert resp.is_bootloader_mode is True
        mock_serial.write.assert_called_once_with(AT_START)

    def test_enter_bootloader_rom_code(self, mock_serial: MagicMock) -> None:
        mock_serial.read.return_value = b"[ rom code mode ]\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.enter_bootloader()
        assert resp.is_rom_code_mode is True
        assert resp.is_bootloader_mode is False

    def test_enter_bootloader_unexpected_falls_back_to_prompt(self, mock_serial: MagicMock) -> None:
        mock_serial.read.side_effect = [b"Unknown\r\n", b">"]
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.enter_bootloader()
        assert resp.is_bootloader_mode is True
        assert resp.is_rom_code_mode is False
        assert mock_serial.write.call_args_list[0][0][0] == AT_START
        assert mock_serial.write.call_args_list[1][0][0] == b"\r\n"

    def test_enter_bootloader_timeout_instructs_manual_mode(self, mock_serial: MagicMock) -> None:
        mock_serial.read.return_value = b""
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=0.01)
        with pytest.raises(TimeoutError, match="BOOT_SEL"):
            bp.enter_bootloader()

    def test_send_firmware_success(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = (
            b"<<<   download SUCCESS   >>>\r\n"
        )
        bp = BootloaderProtocol(serial=mock_serial, chunk_size=256)
        data = b"\x00" * 512

        resp = bp.send_firmware(data, addr=CODE1_ADDR)
        assert resp.is_download_success is True

        # Verify AT+SEND was sent first
        assert mock_serial.write.call_count >= 2
        first_call = mock_serial.write.call_args_list[0]
        assert first_call[0][0] == AT_SEND

    def test_send_firmware_fail(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = (
            b"download fail,please check boot download mode\r\n"
        )
        bp = BootloaderProtocol(serial=mock_serial, chunk_size=256)
        data = b"\x00" * 512

        resp = bp.send_firmware(data, addr=CODE1_ADDR)
        assert resp.is_download_fail is True

    def test_send_firmware_progress_callback(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"OK\r\n"
        bp = BootloaderProtocol(serial=mock_serial, chunk_size=256)
        data = b"\x00" * 512

        callback_calls: list[tuple[int, int]] = []

        def _cb(sent: int, total: int) -> None:
            callback_calls.append((sent, total))

        bp.progress_callback = _cb
        bp.send_firmware(data, addr=CODE1_ADDR)

        # Should have called callback for each chunk
        assert len(callback_calls) >= 1
        # Last call should show all bytes sent
        assert callback_calls[-1] == (512, 512)

    def test_reboot(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.side_effect = TimeoutError("no data")
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.reboot()
        mock_serial.write.assert_called_once_with(AT_REBOOT)
        # Should return OK even on timeout (chip may have rebooted)
        assert resp.is_ok is True

    def test_reboot_with_response(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"Rebooting...\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.reboot()
        mock_serial.write.assert_called_once_with(AT_REBOOT)
        # Reboot returns parsed response (is_ok depends on content)
        assert resp.text == "Rebooting..."

    def test_write_memory(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"OK\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.write_memory(0x100000, 0xDEADBEEF)
        assert resp.is_ok is True
        # Verify command format
        write_calls = mock_serial.write.call_args_list
        cmd_call = write_calls[0]
        cmd = cmd_call[0][0]
        assert cmd.startswith(b"AT+wmem")
        assert b"0x00100000" in cmd
        assert b"0xdeadbeef" in cmd.lower()

    def test_write_memory_invalid_value(self, mock_serial: MagicMock) -> None:
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        with pytest.raises(ValueError):
            bp.write_memory(0x100000, 0x100000000)  # 33-bit value

    def test_read_memory(self, mock_serial: MagicMock) -> None:
        # New 6446 hex block format
        mock_serial.read_until.return_value = (
            b"AT+WIFI_ETF_RMEM 00000000 4\r\n"
            b"{00000000: DEADBEEF} DEADBEEF 00000000 00000000 00000000\r\n"
            b"+OK"
        )
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.read_memory(0x00000000, 4)
        # Verify command format (no 0x prefix for 6446)
        write_calls = mock_serial.write.call_args_list
        cmd_call = write_calls[0]
        cmd = cmd_call[0][0]
        assert cmd.startswith(b"AT+WIFI_ETF_RMEM")
        assert b"00000000" in cmd
        # rmem/ETF dumps print 32-bit word values; raw memory is little-endian.
        assert resp.raw == bytes([0xEF, 0xBE, 0xAD, 0xDE])

    def test_read_flash_uses_bootloader_flash_mapping(self, mock_serial: MagicMock) -> None:
        mock_serial.read.return_value = (
            b"Memory at 00400000:\r\n"
            b"  00400000: DEADBEEF\r\n"
            b"+OK"
        )
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)

        resp = bp.read_flash(0x000000, 4)

        cmd = mock_serial.write.call_args_list[0][0][0]
        assert cmd == b"rmem 400000\r\n"
        assert resp.raw == bytes([0xEF, 0xBE, 0xAD, 0xDE])

    def test_get_modem_info(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"AT+GMR response\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.get_modem_info()
        mock_serial.write.assert_called_once_with(AT_GMR)
        assert resp.text == "AT+GMR response"

    def test_get_sdk_version(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"SDK version 1.0\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.get_sdk_version()
        mock_serial.write.assert_called_once_with(AT_GET_SDK_VER)
        assert resp.text == "SDK version 1.0"

    def test_get_hw_version(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"Hardware version 2.0\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.get_hw_version()
        mock_serial.write.assert_called_once_with(AT_VENVER)
        assert resp.text == "Hardware version 2.0"

    def test_get_fwinfo(self, mock_serial: MagicMock) -> None:
        mock_serial.read_until.return_value = b"Firmware info\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.get_modem_info()
        # AT+WIFI_GET_FWINFO is same as AT+GMR in the protocol
        assert resp.text == "Firmware info"

    def test_burn_firmware_all(self, mock_serial: MagicMock) -> None:
        """Test full burn sequence with all firmware components."""
        mock_serial.read.return_value = b"[ bootloader mode ]\r\n"
        mock_serial.read_until.return_value = (
            b"<<<   download SUCCESS   >>>\r\n"
        )
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        spec = FirmwareSpec(
            bootloader="/tmp/boot.bin",
            code1="/tmp/code1.bin",
            code2="/tmp/code2.bin",
            keyfile="/tmp/key.txt",
        )

        with patch("builtins.open"):
            resp = bp.burn_firmware(spec)
            assert resp.is_download_success is True

    def test_burn_firmware_partial(self, mock_serial: MagicMock) -> None:
        """Test burn with only CODE1."""
        mock_serial.read_until.return_value = (
            b"<<<   download SUCCESS   >>>\r\n"
        )
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        spec = FirmwareSpec(code1="/tmp/code1.bin")

        with patch("builtins.open"):
            resp = bp.burn_firmware(spec)
            assert resp.is_download_success is True

    def test_burn_firmware_fail(self, mock_serial: MagicMock) -> None:
        """Test burn that fails on CODE1."""
        mock_serial.read_until.return_value = (
            b"download fail\r\n"
        )
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        spec = FirmwareSpec(code1="/tmp/code1.bin")

        with patch("builtins.open"):
            resp = bp.burn_firmware(spec)
            assert resp.is_download_fail is True

    def test_bootloader_max_size(self, mock_serial: MagicMock) -> None:
        """Test that bootloader exceeds max size."""
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        with patch("builtins.open") as mock_open:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = lambda *a: False
            mock_open.return_value.read.return_value = b"\x00" * (
                BOOTLOADER_MAX_SIZE + 1
            )
            with pytest.raises(ValueError):
                bp.send_bootloader("/tmp/boot.bin")

    def test_context_manager(self, mock_serial: MagicMock) -> None:
        """Test BootloaderProtocol as context manager."""
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        with bp:
            pass
        mock_serial.close.assert_called_once()

    def test_progress_callback_none(self, mock_serial: MagicMock) -> None:
        """Test that progress_callback is None by default."""
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        assert bp.progress_callback is None

    def test_send_firmware_chunk_boundary(self, mock_serial: MagicMock) -> None:
        """Test firmware sent in correct chunk sizes."""
        mock_serial.read_until.return_value = b"OK\r\n"
        bp = BootloaderProtocol(serial=mock_serial, chunk_size=128)
        data = b"\x00" * 256  # Exactly 2 chunks

        resp = bp.send_firmware(data, addr=CODE1_ADDR)
        assert resp.is_ok is True

        # AT+SEND + 2 chunks + newline response
        assert mock_serial.write.call_count >= 3

    def test_send_firmware_small_data(self, mock_serial: MagicMock) -> None:
        """Test firmware smaller than chunk size."""
        mock_serial.read_until.return_value = b"OK\r\n"
        bp = BootloaderProtocol(serial=mock_serial, chunk_size=1024)
        data = b"\x00" * 16  # 16 bytes

        resp = bp.send_firmware(data, addr=CODE1_ADDR)
        assert resp.is_ok is True

    def test_write_memory_addr_0x100000(self, mock_serial: MagicMock) -> None:
        """Test writing to CODE1 address."""
        mock_serial.read_until.return_value = b"OK\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.write_memory(0x100000, 0x12345678)
        assert resp.is_ok is True
        write_calls = mock_serial.write.call_args_list
        cmd = write_calls[0][0][0]
        assert b"0x00100000" in cmd

    def test_read_memory_multiple_bytes(self, mock_serial: MagicMock) -> None:
        """Test reading multiple bytes."""
        mock_serial.read_until.return_value = b"0x16a00020:0xDEADBEEF\r\n"
        bp = BootloaderProtocol(serial=mock_serial, boot_timeout=1.0)
        resp = bp.read_memory(0x16a00020, 8)
        assert resp.text == "0x16a00020:0xDEADBEEF"
