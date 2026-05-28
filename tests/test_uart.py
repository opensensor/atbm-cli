"""Tests for serial port management (F2)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from atbm6441_cli.protocol.uart import SerialManager


@pytest.fixture
def mock_serial():
    """Create a mock serial.Serial instance."""
    mock = MagicMock()
    mock.is_open = True
    mock.read.return_value = b"AT+VENVER\r\nOK\r\n"
    mock.write.return_value = 10
    return mock


class TestSerialManager:
    """Tests for SerialManager."""

    def test_open_with_port(self, mock_serial):
        """Test opening with explicit port."""
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial) as mock_cls:
            mgr = SerialManager(port="/dev/ttyUSB0", baudrate=115200)
            mgr.open()
            assert mgr.is_open
            assert mgr._port == "/dev/ttyUSB0"
            mock_cls.assert_called_once_with(
                port="/dev/ttyUSB0",
                baudrate=115200,
                bytesize=8,
                parity="N",  # PARITY_NONE = 'N'
                stopbits=1,  # STOPBITS_ONE = 1
                timeout=1.0,
            )

    def test_open_with_port_override(self, mock_serial):
        """Test opening with port override."""
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
            mgr = SerialManager(port="/dev/ttyUSB0", baudrate=115200)
            mgr.open(port="/dev/ttyUSB1")
            assert mgr.is_open
            assert mgr._port == "/dev/ttyUSB1"

    def test_close(self, mock_serial):
        """Test closing the serial port."""
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
            mgr = SerialManager(port="/dev/ttyUSB0")
            mgr.open()
            assert mgr.is_open
            mgr.close()
            assert not mgr.is_open
            mock_serial.close.assert_called_once()

    def test_close_when_not_open(self):
        """Test closing when port is not open (no error)."""
        mgr = SerialManager(port="/dev/ttyUSB0")
        mgr.close()  # Should not raise

    def test_write_raises_when_not_open(self):
        """Test that write raises RuntimeError when port is not open."""
        mgr = SerialManager(port="/dev/ttyUSB0")
        with pytest.raises(RuntimeError, match="Serial port is not open"):
            mgr.write(b"test")

    def test_read_raises_when_not_open(self):
        """Test that read raises RuntimeError when port is not open."""
        mgr = SerialManager(port="/dev/ttyUSB0")
        with pytest.raises(RuntimeError, match="Serial port is not open"):
            mgr.read()

    def test_read_until_raises_when_not_open(self):
        """Test that read_until raises RuntimeError when port is not open."""
        mgr = SerialManager(port="/dev/ttyUSB0")
        with pytest.raises(RuntimeError, match="Serial port is not open"):
            mgr.read_until()

    def test_send_and_read_raises_when_not_open(self):
        """Test that send_and_read raises RuntimeError when port is not open."""
        mgr = SerialManager(port="/dev/ttyUSB0")
        with pytest.raises(RuntimeError, match="Serial port is not open"):
            mgr.send_and_read(b"test")

    def test_context_manager(self, mock_serial):
        """Test context manager usage."""
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
            with SerialManager(port="/dev/ttyUSB0") as mgr:
                assert mgr.is_open
            assert not mgr.is_open
            mock_serial.close.assert_called_once()

    def test_auto_detect_found(self, mock_serial):
        """Test auto-detect with FT232 device found."""
        mock_port = MagicMock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.vid = int("0403", 16)
        mock_port.pid = "6001"
        mock_port.description = "FT232USB"

        with patch("atbm6441_cli.protocol.uart.serial.tools.list_ports.comports", return_value=[mock_port]):
            with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
                mgr = SerialManager()
                mgr.open()
                assert mgr._port == "/dev/ttyUSB0"

    def test_auto_detect_fallback(self, mock_serial):
        """Test auto-detect fallback to first available port."""
        mock_port = MagicMock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.vid = 0x1234  # Not FT232
        mock_port.pid = "5678"
        mock_port.description = "Generic USB Serial"

        with patch("atbm6441_cli.protocol.uart.serial.tools.list_ports.comports", return_value=[mock_port]):
            with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
                mgr = SerialManager()
                mgr.open()
                assert mgr._port == "/dev/ttyUSB0"

    def test_auto_detect_no_ports(self):
        """Test auto-detect with no ports found."""
        with patch("atbm6441_cli.protocol.uart.serial.tools.list_ports.comports", return_value=[]):
            mgr = SerialManager()
            with pytest.raises(ValueError, match="No serial ports found"):
                mgr.open()

    def test_write(self, mock_serial):
        """Test writing bytes to the port."""
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
            mgr = SerialManager(port="/dev/ttyUSB0")
            mgr.open()
            written = mgr.write(b"hello")
            assert written == 10
            mock_serial.write.assert_called_once_with(b"hello")

    def test_read(self, mock_serial):
        """Test reading bytes from the port."""
        mock_serial.read.return_value = b"response"
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial):
            mgr = SerialManager(port="/dev/ttyUSB0")
            mgr.open()
            data = mgr.read(length=8)
            assert data == b"response"
            mock_serial.read.assert_called_once_with(length=8)

    def test_read_until(self, mock_serial):
        """Test reading until sentinel."""
        mock_serial.read.side_effect = [b"AT+VENVER\r", b"\n", b""]
        with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial) as mock_cls:
            mgr = SerialManager(port="/dev/ttyUSB0")
            mgr.open()
            data = mgr.read_until(sentinel=b"\r\n")
            assert b"AT+VENVER" in data
            assert b"\r\n" in data
            mock_cls.assert_called_once()

    def test_custom_baudrates(self, mock_serial):
        """Test opening with different baud rates."""
        for baud in [115200, 1000000, 1500000]:
            with patch("atbm6441_cli.protocol.uart.serial.Serial", return_value=mock_serial) as mock_cls:
                mgr = SerialManager(port="/dev/ttyUSB0", baudrate=baud)
                mgr.open()
                call_kwargs = mock_cls.call_args[1]
                assert call_kwargs["baudrate"] == baud
