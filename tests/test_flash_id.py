"""Tests for FlashIdReader — JEDEC ID flash discovery."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from atbm6441_cli.protocol.flash_id import CAPACITY_MAP, FlashIdReader, FlashInfo


class TestFlashInfo:
    """Tests for the FlashInfo dataclass."""

    def test_frozen(self) -> None:
        """FlashInfo should be immutable."""
        from dataclasses import FrozenInstanceError

        info = FlashInfo(manufacturer_id=0xEF, device_id=0x4018, capacity_id=0x18, size_bytes=0x400000)
        with pytest.raises(FrozenInstanceError):
            info.manufacturer_id = 0x20

    def test_manufacturer_name_known(self) -> None:
        """Known manufacturer IDs should return names."""
        info = FlashInfo(manufacturer_id=0xEF, device_id=0x4018, capacity_id=0x18, size_bytes=0x400000)
        assert info.manufacturer_name == "Winbond"

    def test_manufacturer_name_unknown(self) -> None:
        """Unknown manufacturer IDs should return 'unknown'."""
        info = FlashInfo(manufacturer_id=0xFF, device_id=0x0000, capacity_id=0x00, size_bytes=0)
        assert info.manufacturer_name == "unknown"

    def test_size_human_4mb(self) -> None:
        """4MB should return '4MB'."""
        info = FlashInfo(manufacturer_id=0xEF, device_id=0x4018, capacity_id=0x18, size_bytes=0x400000)
        assert info.size_human == "4MB"

    def test_size_human_1mb(self) -> None:
        """1MB should return '1MB'."""
        info = FlashInfo(manufacturer_id=0xEF, device_id=0x1644, capacity_id=0x16, size_bytes=0x100000)
        assert info.size_human == "1MB"

    def test_size_human_unknown(self) -> None:
        """Unknown size should return byte count."""
        info = FlashInfo(manufacturer_id=0xEF, device_id=0x0000, capacity_id=0x00, size_bytes=0x500000)
        assert info.size_human == "5242880 bytes"


class TestParseCapacity:
    """Tests for the capacity_id → size mapping."""

    def test_1mb(self) -> None:
        assert FlashIdReader.parse_capacity(0x16) == 0x100000

    def test_2mb(self) -> None:
        assert FlashIdReader.parse_capacity(0x17) == 0x200000

    def test_4mb(self) -> None:
        assert FlashIdReader.parse_capacity(0x18) == 0x400000

    def test_8mb(self) -> None:
        assert FlashIdReader.parse_capacity(0x19) == 0x800000

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown JEDEC capacity_id"):
            FlashIdReader.parse_capacity(0x00)

    def test_unknown_suggests_override(self) -> None:
        with pytest.raises(ValueError, match="--flash-size"):
            FlashIdReader.parse_capacity(0xFF)

    def test_capacity_map_complete(self) -> None:
        """CAPACITY_MAP should be non-empty and have expected entries."""
        assert len(CAPACITY_MAP) >= 4
        assert 0x16 in CAPACITY_MAP
        assert 0x17 in CAPACITY_MAP
        assert 0x18 in CAPACITY_MAP
        assert 0x19 in CAPACITY_MAP


class TestFlashIdReader:
    """Tests for FlashIdReader using mock serial."""

    @pytest.fixture
    def mock_serial(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        """Create a mock SerialManager."""
        mock = Mock()
        mock.is_open = True
        mock._timeout = 1.0
        return mock

    def test_read_id_success(self, mock_serial: pytest.Mock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful JEDEC ID read returns FlashInfo."""
        # Simulate 3-byte response: Winbond EF 40 18
        mock_serial._count = 0
        response_bytes = [0xEF, 0x40, 0x18]

        def read_side_effect(length: int = 1) -> bytes:
            if mock_serial._count < len(response_bytes):
                byte = response_bytes[mock_serial._count]
                mock_serial._count += 1
                return bytes([byte])
            return b"\x00"

        monkeypatch.setattr(mock_serial, "write", Mock())
        monkeypatch.setattr(mock_serial, "read", read_side_effect)

        reader = FlashIdReader(mock_serial)
        info = reader.read_id()

        assert info.manufacturer_id == 0xEF
        assert info.device_id == 0x40
        assert info.capacity_id == 0x18
        assert info.size_bytes == 0x400000
        assert info.manufacturer_name == "Winbond"
        assert info.size_human == "4MB"

    def test_read_id_requires_open(self, mock_serial: pytest.Mock) -> None:
        """read_id should raise RuntimeError if serial is not open."""
        mock_serial.is_open = False
        reader = FlashIdReader(mock_serial)
        with pytest.raises(RuntimeError, match="not open"):
            reader.read_id()

    def test_read_id_timeout(self, mock_serial: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
        """read_id should raise TimeoutError if no bytes returned."""
        monkeypatch.setattr(mock_serial, "write", Mock())
        monkeypatch.setattr(mock_serial, "read", lambda length=1: b"")

        reader = FlashIdReader(mock_serial)
        with pytest.raises(TimeoutError, match="Timeout"):
            reader.read_id()
