"""Flash JEDEC ID discovery — determine flash chip size via 0x9F command."""

from __future__ import annotations

import dataclasses
import logging
from typing import Optional

from atbm6441_cli.protocol.uart import SerialManager

logger = logging.getLogger(__name__)

# JEDEC capacity_id → flash size in bytes
CAPACITY_MAP: dict[int, int] = {
    0x16: 0x100000,   # 1 MB
    0x17: 0x200000,   # 2 MB
    0x18: 0x400000,   # 4 MB
    0x19: 0x800000,   # 8 MB
    0x5F: 0x400000,   # 4 MB (ATBM6446 variant)
}


@dataclasses.dataclass(frozen=True)
class FlashInfo:
    """JEDEC ID and size of the SPI flash chip."""
    manufacturer_id: int
    device_id: int
    capacity_id: int
    size_bytes: int

    @property
    def manufacturer_name(self) -> str:
        """Return a human-readable manufacturer name."""
        names: dict[int, str] = {
            0xEF: "Winbond",
            0xC8: "XMC",
            0x20: "Micron",
            0xBF: "SST",
            0x1C: "Spansion",
            0xAD: "Macronix",
        }
        return names.get(self.manufacturer_id, "unknown")

    @property
    def size_human(self) -> str:
        """Return human-readable size string."""
        for name, size in [("8MB", 0x800000), ("4MB", 0x400000), ("2MB", 0x200000), ("1MB", 0x100000)]:
            if self.size_bytes == size:
                return name
        return f"{self.size_bytes} bytes"


class FlashIdReader:
    """Read JEDEC ID from SPI flash chip via UART register ops."""

    JEDEC_READ_CMD = b"\x9F"

    def __init__(self, serial: SerialManager) -> None:
        self._serial = serial

    def read_id(self) -> FlashInfo:
        """Send JEDEC Read ID command (0x9F) and parse response.

        Returns:
            FlashInfo with manufacturer, device, capacity, and size.

        Raises:
            TimeoutError: If no response received within timeout.
            RuntimeError: If serial port is not open.
        """
        if not self._serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        logger.debug("Sending JEDEC Read ID (0x9F) command")
        # Send command byte
        self._serial.write(self.JEDEC_READ_CMD)

        # Read 3 response bytes: manufacturer, device, capacity
        response = bytearray()
        expected_length = 3
        timeout = self._serial._timeout

        while len(response) < expected_length:
            chunk = self._serial.read(length=1)
            if not chunk:
                raise TimeoutError(
                    f"Timeout waiting for JEDEC ID bytes (received {len(response)}/3)"
                )
            response.extend(chunk)

        manufacturer_id = response[0]
        device_id = response[1]
        capacity_id = response[2]

        logger.info(
            "JEDEC ID: manufacturer=0x%02X (%s), device=0x%04X, capacity=0x%02X",
            manufacturer_id,
            FlashInfo(manufacturer_id, device_id, capacity_id, 0).manufacturer_name,
            device_id,
            capacity_id,
        )

        size_bytes = self.parse_capacity(capacity_id)
        flash_info = FlashInfo(
            manufacturer_id=manufacturer_id,
            device_id=device_id,
            capacity_id=capacity_id,
            size_bytes=size_bytes,
        )

        logger.info("Flash chip: %s %s (%d bytes)", flash_info.manufacturer_name, flash_info.size_human, size_bytes)
        return flash_info

    @staticmethod
    def parse_capacity(capacity_id: int) -> int:
        """Map JEDEC capacity_id to flash size in bytes.

        Args:
            capacity_id: The capacity byte from JEDEC ID response.

        Returns:
            Flash size in bytes.

        Raises:
            ValueError: If capacity_id is not recognized.
        """
        if capacity_id in CAPACITY_MAP:
            return CAPACITY_MAP[capacity_id]

        raise ValueError(
            f"Unknown JEDEC capacity_id 0x{capacity_id:02X}. "
            f"Supported: {', '.join(f'0x{k:02X}' for k in sorted(CAPACITY_MAP))}. "
            f"Use --flash-size to override."
        )
