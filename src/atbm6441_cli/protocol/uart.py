"""Serial port management using pyserial."""

from __future__ import annotations

import logging
import time
from typing import BinaryIO

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)

# FT232 VID/PID for auto-detection
FT232_VID = "0403"
FT232_PIDS = {"6001", "6010", "6011", "6014", "6015"}


class SerialManager:
    """Manages a serial port connection for ATBM6441 communication."""

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 1000000,
        timeout: float = 1.0,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: serial.Serial | None = None

    @property
    def is_open(self) -> bool:
        """Whether the serial port is currently open."""
        return self._serial is not None and self._serial.is_open

    def open(self, port: str | None = None) -> None:
        """Open the serial port.

        Args:
            port: Optional port override. Uses configured port if None.

        Raises:
            serial.SerialException: If the port cannot be opened.
            ValueError: If no port is specified and auto-detect fails.
        """
        target_port = port or self._port
        if not target_port:
            target_port = self._auto_detect()

        logger.info("Opening serial port %s at %d baud", target_port, self._baudrate)
        self._serial = serial.Serial(
            port=target_port,
            baudrate=self._baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self._timeout,
        )
        self._port = target_port
        logger.info("Serial port %s opened successfully", target_port)

    def close(self) -> None:
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            logger.info("Closing serial port %s", self._port)
            self._serial.close()
            self._serial = None

    def write(self, data: bytes) -> int:
        """Write bytes to the serial port.

        Args:
            data: Bytes to write.

        Returns:
            Number of bytes written.

        Raises:
            RuntimeError: If the serial port is not open.
        """
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")
        return self._serial.write(data)

    def read(self, length: int = 1, timeout: float | None = None) -> bytes:
        """Read bytes from the serial port.

        Args:
            length: Number of bytes to read.
            timeout: Optional timeout override in seconds.

        Returns:
            Bytes read from the port.

        Raises:
            RuntimeError: If the serial port is not open.
        """
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        effective_timeout = timeout if timeout is not None else self._timeout
        return self._serial.read(size=length)

    def read_until(
        self,
        sentinel: bytes = b"\n",
        timeout: float | None = None,
        expected_length: int = 4096,
    ) -> bytes:
        """Read until a sentinel byte sequence is found.

        Args:
            sentinel: Byte sequence to read until (default: newline).
            timeout: Optional timeout override in seconds.
            expected_length: Maximum bytes to read before giving up.

        Returns:
            Bytes read including the sentinel.

        Raises:
            RuntimeError: If the serial port is not open.
            TimeoutError: If timeout is exceeded before sentinel is found.
        """
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        effective_timeout = timeout if timeout is not None else self._timeout
        start_time = time.time()
        result = bytearray()

        while True:
            remaining = effective_timeout - (time.time() - start_time)
            if remaining <= 0:
                raise TimeoutError(
                    f"Timeout waiting for sentinel {sentinel!r} after {expected_length} bytes"
                )

            chunk = self._serial.read(size=min(expected_length, 256))
            if not chunk:
                # No data available, wait a bit
                time.sleep(0.01)
                continue

            result.extend(chunk)

            if sentinel in result:
                break

            if len(result) > expected_length:
                raise TimeoutError(
                    f"Read more than {expected_length} bytes without finding sentinel {sentinel!r}"
                )

        return bytes(result)

    def send_and_read(
        self,
        data: bytes,
        sentinel: bytes = b"\n",
        timeout: float | None = None,
    ) -> bytes:
        """Send data and read response until sentinel.

        Args:
            data: Bytes to send.
            sentinel: Byte sequence to read until.
            timeout: Optional timeout override.

        Returns:
            Response bytes including sentinel.
        """
        self.write(data)
        return self.read_until(sentinel=sentinel, timeout=timeout)

    @staticmethod
    def _auto_detect() -> str:
        """Auto-detect FT232 serial port.

        Returns:
            Port name (e.g. '/dev/ttyUSB0').

        Raises:
            ValueError: If no FT232 device is found.
        """
        logger.info("Auto-detecting FT232 serial port...")
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if port.vid == int(FT232_VID, 16) and port.pid in FT232_PIDS:
                logger.info("Found FT232 at %s (%s)", port.device, port.description)
                return port.device

        # Fallback: return first available serial port
        if ports:
            logger.warning("No FT232 found, using first available port: %s", ports[0].device)
            return ports[0].device

        raise ValueError("No serial ports found. Connect the ATBM6441 EVK board.")

    def __enter__(self) -> SerialManager:
        """Context manager entry: open the port."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Context manager exit: close the port."""
        self.close()
