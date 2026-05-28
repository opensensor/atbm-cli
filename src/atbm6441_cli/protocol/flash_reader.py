"""Chunked flash read — read flash content in configurable-size chunks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

from atbm6441_cli.protocol.flash_id import FlashIdReader, FlashInfo
from atbm6441_cli.protocol.uart import SerialManager

logger = logging.getLogger(__name__)


class FlashReader:
    """Read flash content in chunks, with auto-size discovery and progress tracking."""

    CHUNK_SIZE: int = 4096
    MAX_RETRIES: int = 3

    def __init__(
        self,
        serial: SerialManager,
        flash_size: int | None = None,
        chunk_size: int | None = None,
        read_chunk_callback: Callable[[int], bytes] | None = None,
    ) -> None:
        """
        Args:
            serial: Open SerialManager instance.
            flash_size: Known flash size in bytes. If None, auto-discover via JEDEC.
            chunk_size: Size of each read chunk in bytes. Defaults to 4096.
            read_chunk_callback: Custom callback to read a single chunk. If None,
                uses the default read_chunk implementation (placeholder for protocol).
        """
        self._serial = serial
        self._flash_size = flash_size
        self._chunk_size = chunk_size or self.CHUNK_SIZE
        self._read_chunk_callback = read_chunk_callback or self._default_read_chunk

    @property
    def flash_size(self) -> int:
        """Return the resolved flash size in bytes."""
        if self._flash_size is None:
            self._flash_size = self._discover_flash_size()
        return self._flash_size

    def _discover_flash_size(self) -> int:
        """Auto-discover flash size via JEDEC ID."""
        logger.info("Auto-discovering flash size via JEDEC ID")
        id_reader = FlashIdReader(self._serial)
        info = id_reader.read_id()
        return info.size_bytes

    def read_all(self, progress_callback: Callable[[int, int], None] | None = None) -> bytes:
        """Read the entire flash content.

        Args:
            progress_callback: Called with (bytes_read, total_size) after each chunk.

        Returns:
            Full flash content as bytes.
        """
        size = self.flash_size
        total_chunks = (size + self._chunk_size - 1) // self._chunk_size
        result = bytearray()

        for i in range(total_chunks):
            addr = i * self._chunk_size
            remaining = size - len(result)
            chunk_size = min(self._chunk_size, remaining)

            data = self._read_chunk(addr, chunk_size)
            result.extend(data)

            if progress_callback:
                progress_callback(len(result), size)

            logger.debug("Read chunk %d/%d (%d/%d bytes)", i + 1, total_chunks, len(result), size)

        return bytes(result[:size])

    def read_range(self, addr: int, length: int, progress_callback: Callable[[int, int], None] | None = None) -> bytes:
        """Read a specific address range.

        Args:
            addr: Starting flash address.
            length: Number of bytes to read.
            progress_callback: Called with (bytes_read, total_length) after each chunk.

        Returns:
            Read content as bytes.
        """
        total_chunks = (length + self._chunk_size - 1) // self._chunk_size
        result = bytearray()

        for i in range(total_chunks):
            chunk_addr = addr + i * self._chunk_size
            remaining = length - len(result)
            chunk_size = min(self._chunk_size, remaining)

            data = self._read_chunk(chunk_addr, chunk_size)
            result.extend(data)

            if progress_callback:
                progress_callback(len(result), length)

        return bytes(result[:length])

    def _read_chunk(self, addr: int, size: int | None = None) -> bytes:
        """Read a single chunk from the given address.

        Retries up to MAX_RETRIES times on failure.

        Args:
            addr: Flash address to read from.
            size: Number of bytes to read. Defaults to CHUNK_SIZE.

        Returns:
            Read bytes.

        Raises:
            RuntimeError: If all retries fail.
        """
        chunk_size = size or self._chunk_size
        last_error: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                data = self._read_chunk_callback(addr)
                if len(data) < chunk_size:
                    # Pad with zeros if we got less than expected
                    data = data + b"\x00" * (chunk_size - len(data))
                return data
            except Exception as e:
                last_error = e
                logger.warning(
                    "Chunk read at 0x%06X failed (attempt %d/%d): %s",
                    addr, attempt, self.MAX_RETRIES, e,
                )

        raise RuntimeError(
            f"Failed to read chunk at 0x{addr:06X} after {self.MAX_RETRIES} attempts: {last_error}"
        )

    @staticmethod
    def _default_read_chunk(addr: int) -> bytes:
        """Default chunk read — placeholder for protocol implementation.

        This will be replaced by the actual protocol layer (T2.4 register ops)
        once the handshake and register read/write commands are implemented.

        Args:
            addr: Flash address to read from.

        Returns:
            Placeholder bytes (all zeros).

        Raises:
            NotImplementedError: Always — protocol not yet implemented.
        """
        raise NotImplementedError(
            "FlashReader._default_read_chunk is a placeholder. "
            "Provide a read_chunk_callback or implement protocol layer (T2.4)."
        )
