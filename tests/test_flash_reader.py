"""Tests for FlashReader — chunked flash readback."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from atbm6441_cli.protocol.flash_reader import FlashReader


class TestFlashReader:
    """Tests for the FlashReader class."""

    @pytest.fixture
    def mock_serial(self) -> Mock:
        """Create a mock SerialManager."""
        serial = Mock()
        serial.is_open = True
        serial._timeout = 1.0
        return serial

    @pytest.fixture
    def mock_bootloader(self, mock_serial: Mock) -> Mock:
        """Create a mock BootloaderProtocol."""
        bootloader = Mock()
        bootloader._serial = mock_serial
        # Return 4KB of sequential data for any address
        def mock_read_flash(address: int, length: int) -> Mock:
            response = Mock()
            response.raw = bytes([address & 0xFF] * length)
            return response
        bootloader.read_flash = mock_read_flash
        return bootloader

    @pytest.fixture
    def reader_with_bootloader(self, mock_serial: Mock, mock_bootloader: Mock) -> FlashReader:
        """Create a FlashReader with a mock bootloader."""
        reader = FlashReader(mock_serial, flash_size=0x10000, bootloader=mock_bootloader)
        return reader

    def test_flash_size_resolved(self, mock_serial: Mock) -> None:
        """flash_size property returns the configured size."""
        reader = FlashReader(mock_serial, flash_size=0x400000)
        assert reader.flash_size == 0x400000

    def test_read_all_chunks(self, reader_with_bootloader: FlashReader) -> None:
        """read_all returns exactly flash_size bytes."""
        reader = reader_with_bootloader
        data = reader.read_all()
        assert len(data) == 0x10000

    def test_read_all_chunk_boundary(self, reader_with_bootloader: FlashReader) -> None:
        """Last chunk reads exactly remaining bytes."""
        # Use a size that doesn't align to chunk boundary
        reader = FlashReader(
            reader_with_bootloader._serial,
            flash_size=0x10003,
            bootloader=reader_with_bootloader._bootloader,
        )
        data = reader.read_all()
        assert len(data) == 0x10003

    def test_read_range(self, reader_with_bootloader: FlashReader) -> None:
        """read_range returns correct number of bytes."""
        data = reader_with_bootloader.read_range(addr=0x1000, length=0x800)
        assert len(data) == 0x800

    def test_read_range_exact_chunks(self, reader_with_bootloader: FlashReader) -> None:
        """read_range with exact chunk size reads one chunk."""
        data = reader_with_bootloader.read_range(addr=0x0, length=0x1000)
        assert len(data) == 0x1000

    def test_read_all_progress_callback(self, reader_with_bootloader: FlashReader) -> None:
        """Progress callback is called after each chunk."""
        calls: list[tuple[int, int]] = []

        def callback(bytes_read: int, total: int) -> None:
            calls.append((bytes_read, total))

        reader_with_bootloader.read_all(progress_callback=callback)

        # 0x10000 / 0x1000 = 16 chunks
        assert len(calls) == 16
        assert calls[-1] == (0x10000, 0x10000)

    def test_read_range_progress_callback(self, reader_with_bootloader: FlashReader) -> None:
        """Progress callback is called for read_range."""
        calls: list[tuple[int, int]] = []

        def callback(bytes_read: int, total: int) -> None:
            calls.append((bytes_read, total))

        reader_with_bootloader.read_range(addr=0x0, length=0x2000, progress_callback=callback)

        # 0x2000 / 0x1000 = 2 chunks
        assert len(calls) == 2
        assert calls[-1] == (0x2000, 0x2000)

    def test_no_bootloader_raises(self, mock_serial: Mock) -> None:
        """Without bootloader, _read_chunk raises RuntimeError."""
        reader = FlashReader(mock_serial, flash_size=0x1000)
        with pytest.raises(RuntimeError, match="No bootloader instance provided"):
            reader._read_chunk(0x0)

    def test_chunk_read_retry_on_failure(self, mock_serial: Mock, mock_bootloader: Mock) -> None:
        """_read_chunk retries MAX_RETRIES times on failure."""
        call_count = 0

        def failing_read_flash(address: int, length: int) -> Mock:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Simulated failure")

        mock_bootloader.read_flash = failing_read_flash
        reader = FlashReader(mock_serial, flash_size=0x1000, bootloader=mock_bootloader)

        with pytest.raises(RuntimeError, match="Failed to read chunk"):
            reader._read_chunk(0x0)

        assert call_count == FlashReader.MAX_RETRIES

    def test_chunk_read_short_data_padded(self, mock_serial: Mock, mock_bootloader: Mock) -> None:
        """Short chunk data is padded with zeros."""
        def short_read_flash(address: int, length: int) -> Mock:
            response = Mock()
            response.raw = b"\xAB"  # Only 1 byte
            return response

        mock_bootloader.read_flash = short_read_flash
        reader = FlashReader(mock_serial, flash_size=0x1000, bootloader=mock_bootloader)

        # CHUNK_SIZE is 4096, callback returns 1 byte
        data = reader._read_chunk(0x0)
        assert len(data) == FlashReader.CHUNK_SIZE
        assert data[0] == 0xAB
        # Rest should be zeros
        assert data[1:] == b"\x00" * (FlashReader.CHUNK_SIZE - 1)

    def test_read_all_short_last_chunk_padded(self, mock_serial: Mock, mock_bootloader: Mock) -> None:
        """Last chunk padding doesn't exceed flash_size."""
        def callback(address: int, length: int) -> Mock:
            response = Mock()
            response.raw = b"\xFF"  # 1 byte
            return response

        mock_bootloader.read_flash = callback
        reader = FlashReader(mock_serial, flash_size=0x1003, bootloader=mock_bootloader)

        data = reader.read_all()
        assert len(data) == 0x1003

    def test_chunk_size_override(self, mock_serial: Mock, mock_bootloader: Mock) -> None:
        """Custom chunk_size is respected."""
        calls: list[int] = []

        def track_read_flash(address: int, length: int) -> Mock:
            calls.append(address)
            response = Mock()
            response.raw = b"\x00" * 2048
            return response

        mock_bootloader.read_flash = track_read_flash
        reader = FlashReader(
            mock_serial,
            flash_size=0x4000,
            chunk_size=2048,
            bootloader=mock_bootloader,
        )

        data = reader.read_all()
        assert len(data) == 0x4000
        # 0x4000 (16384) / 2048 = 8 chunks
        assert len(calls) == 8
        assert calls[0] == 0x0
        assert calls[1] == 0x800

    def test_read_range_partial_last_chunk(self, reader_with_bootloader: FlashReader) -> None:
        """read_range with non-aligned length handles partial last chunk."""
        data = reader_with_bootloader.read_range(addr=0x0, length=0x1500)
        assert len(data) == 0x1500
