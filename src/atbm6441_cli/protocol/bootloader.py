"""ATBM6441 bootloader protocol — AT command interface for firmware download.

Protocol discovered from Altobem WIFI IOT GUI V1.0.52:

1. Open UART at 1,000,000 baud (24MHz crystal) or 1,500,000 (16MHz)
2. Send ``AT+START\r\n`` → chip enters bootloader mode
3. Wait for ``[ bootloader mode ]`` response
4. Send ``AT+SEND\r\n`` → chip expects firmware data
5. Send firmware data in raw binary chunks
6. Wait for ``<<<   download SUCCESS   >>>`` or ``download fail``
7. Send ``AT+REBOOT\r\n`` → chip reboots with new firmware

Firmware image layout:
    - Bootloader:    0x000000 (max 48 KB)
    - KEY data:      0x008000 (key1), 0x101000 (key2)
    - CODE1 (ICCM):  0x010000  (fw_update1.bin)
    - CODE2 (Flash): 0x040000  (fw_update2.bin)

AT commands:
    - ``AT+START``          Enter bootloader mode
    - ``AT+SEND``           Start firmware data transfer
    - ``AT+REBOOT``         Reboot chip after burn
    - ``AT+wmem <addr> <val>``  Write memory (address, 32-bit value)
    - ``AT+WIFI_ETF_RMEM <addr> <len>``  Read memory
    - ``AT+GMR``            Get modem info
    - ``AT+GET_SDK_VER``    Get SDK version
    - ``AT+VENVER``         Get hardware version
    - ``AT+PRINT 0/1``      Control verbose output
    - ``AT+WIFI_GET_FWINFO``  Get firmware info
"""

from __future__ import annotations

import logging
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .uart import SerialManager

logger = logging.getLogger(__name__)

# ── Firmware image layout addresses ──────────────────────────────────────

BOOTLOADER_ADDR = 0x000000
KEY1_ADDR = 0x008000
KEY2_ADDR = 0x101000
CODE1_ADDR = 0x010000
CODE2_ADDR = 0x040000

BOOTLOADER_MAX_SIZE = 48 * 1024  # 48 KB
FLASH_MEMORY_BASE = 0x00400000  # SDK flash.h: FLASH_BASE for ATBM6441/Hera

# ── AT command constants ─────────────────────────────────────────────────

AT_START = b"AT+START\r\n"
AT_SEND = b"AT+SEND\r\n"
AT_REBOOT = b"AT+REBOOT\r\n"
AT_GMR = b"AT+GMR\r\n"
AT_GET_SDK_VER = b"AT+GET_SDK_VER\r\n"
AT_VENVER = b"AT+VENVER\r\n"
AT_PRINT_ON = b"AT+PRINT 1\r\n"
AT_PRINT_OFF = b"AT+PRINT 0\r\n"
AT_WIFI_GET_FWINFO = b"AT+WIFI_GET_FWINFO\r\n"
AT_WIFI_STATUS = b"AT+WIFI_STATUS\r\n"

# ── Response markers ─────────────────────────────────────────────────────

MARKER_BOOTLOADER_MODE = b"[ bootloader mode ]"
MARKER_ROM_CODE_MODE = b"[ rom code mode ]"
MARKER_BOOT_PROMPT = b">"
MARKER_DOWNLOAD_SUCCESS = b"download SUCCESS"
MARKER_DOWNLOAD_FAIL = b"download fail"
MARKER_OK = b"OK"
MARKER_ERROR = b"ERROR"


@dataclass
class BootloaderResponse:
    """Parsed response from the bootloader."""

    raw: bytes
    is_ok: bool = False
    is_error: bool = False
    is_bootloader_mode: bool = False
    is_rom_code_mode: bool = False
    is_download_success: bool = False
    is_download_fail: bool = False
    text: str = ""


def _parse_response(raw: bytes) -> BootloaderResponse:
    """Parse a bootloader response into a structured object."""
    resp = BootloaderResponse(raw=raw)

    try:
        resp.text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        resp.text = repr(raw)

    if MARKER_BOOTLOADER_MODE in raw or raw.rstrip().endswith(MARKER_BOOT_PROMPT):
        resp.is_bootloader_mode = True
    if MARKER_ROM_CODE_MODE in raw:
        resp.is_rom_code_mode = True
    if MARKER_DOWNLOAD_SUCCESS in raw:
        resp.is_download_success = True
    if MARKER_DOWNLOAD_FAIL in raw:
        resp.is_download_fail = True
    if MARKER_OK in raw:
        resp.is_ok = True
    if MARKER_ERROR in raw:
        resp.is_error = True

    return resp


def _format_serial_bytes(data: bytes, limit: int = 256) -> str:
    """Format a serial byte chunk for live monitor/debug output."""
    shown = data[:limit]
    text = shown.decode("utf-8", errors="replace")
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    hex_text = shown.hex(" ")
    suffix = " ..." if len(data) > limit else ""
    return f"{len(data)} bytes ascii={text!r}{suffix} hex={hex_text}{suffix}"


def _parse_hex_memory_response(
    raw: bytes,
    expected_length: int,
    base_address: int | None = None,
) -> bytes:
    """Parse hex block memory response from AT+WIFI_ETF_RMEM.

    Response format (6446/6447):
        AT+WIFI_ETF_RMEM 00002000 4096
        {00000000: fa37001e} fa37001e 45290089 45290089 45290089{00000010: 45290089} ...
        +OK

    Each block: {addr: 4bytes} 16bytes (4 words × 4 bytes)
    Total per block: 20 bytes

    Args:
        raw: Raw response bytes.
        expected_length: Number of bytes expected.

    Returns:
        Parsed bytes.
    """
    import re
    text = raw.decode("utf-8", errors="replace")

    result = bytearray(expected_length)
    parsed_any = False

    def write_word(addr: int, word: str) -> None:
        nonlocal parsed_any
        if base_address is not None and addr >= base_address:
            addr -= base_address
        for byte_idx in range(4):
            pos = addr + byte_idx
            if 0 <= pos < expected_length:
                hex_pos = byte_idx * 2
                result[pos] = int(word[hex_pos:hex_pos + 2], 16)
                parsed_any = True

    # ETF dump format: {00000000: fa37001e} 45290089 ...
    block_pattern = re.compile(r"\{([0-9a-fA-F]{1,8}):\s*([0-9a-fA-F]{8})\}")
    matches = list(block_pattern.finditer(text))
    for idx, match in enumerate(matches):
        addr = int(match.group(1), 16)
        words = [match.group(2)]
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        trailing_text = text[match.end():block_end]
        words.extend(
            re.findall(r"(?<![0-9a-fA-F])([0-9a-fA-F]{8})(?![0-9a-fA-F])", trailing_text)
        )
        for word_idx, word in enumerate(words):
            write_word(addr + word_idx * 4, word)

    # CLI/bootloader dump format: 00400000: DEADBEEF [more words...]
    line_pattern = re.compile(r"^\s*(?:0x)?([0-9a-fA-F]{1,8})\s*:\s*(.*)$", re.MULTILINE)
    for match in line_pattern.finditer(text):
        addr = int(match.group(1), 16)
        words = re.findall(r"(?<![0-9a-fA-F])(?:0x)?([0-9a-fA-F]{8})(?![0-9a-fA-F])", match.group(2))
        for word_idx, word in enumerate(words):
            write_word(addr + word_idx * 4, word)

    if not parsed_any and expected_length:
        raise ValueError("No hex memory data found in response")

    return bytes(result)


@dataclass
class FirmwareSpec:
    """Specification for firmware images to burn.

    Args:
        bootloader: Path to bootloader binary (max 48 KB, addr 0x000000)
        code1: Path to CODE1/ICCM binary (addr 0x010000)
        code2: Path to CODE2/Flash binary (addr 0x040000)
        keyfile: Path to KEY file (CSV/TXT)
        key1_addr: Address for key1 data (default: 0x008000)
        key2_addr: Address for key2 data (default: 0x101000)
        force: Force destructive operations
    """

    bootloader: Optional[str] = None
    code1: Optional[str] = None
    code2: Optional[str] = None
    keyfile: Optional[str] = None
    mac: Optional[str] = None
    key1_addr: int = KEY1_ADDR
    key2_addr: int = KEY2_ADDR
    force: bool = False


class BootloaderProtocol:
    """AT command protocol for ATBM6441 bootloader firmware download.

    Usage::

        bm = BootloaderProtocol(serial_manager)
        try:
            # Enter bootloader mode
            resp = bm.enter_bootloader()
            if resp.is_bootloader_mode:
                print("Bootloader mode entered")

            # Send firmware
            resp = bm.send_firmware(b"\\x00\\x01\\x02...", addr=0x010000)
            if resp.is_download_success:
                print("Firmware downloaded")

            # Reboot
            bm.reboot()
        finally:
            bm.close()
    """

    def __init__(
        self,
        serial: SerialManager,
        chunk_size: int = 1024,
        send_timeout: float = 30.0,
        boot_timeout: float = 5.0,
        serial_monitor: bool = False,
    ) -> None:
        """Initialize the bootloader protocol.

        Args:
            serial: Open SerialManager instance.
            chunk_size: Data chunk size for firmware transfer (default: 1024).
            send_timeout: Timeout for firmware send operation (seconds).
            boot_timeout: Timeout for bootloader mode entry (seconds).
            serial_monitor: Mirror bootloader TX/RX chunks to stderr.
        """
        self._serial = serial
        self._chunk_size = chunk_size
        self._send_timeout = send_timeout
        self._boot_timeout = boot_timeout
        self._serial_monitor = serial_monitor
        self._progress_callback: Optional[Callable[[int, int], None]] = None

    def _monitor_serial(self, direction: str, data: bytes) -> None:
        message = f"{direction} {_format_serial_bytes(data)}"
        if self._serial_monitor:
            print(message, file=sys.stderr, flush=True)
        else:
            logger.debug(message)

    def _monitor_idle(self, elapsed: float, markers: tuple[bytes, ...], buffered: int) -> None:
        marker_text = ", ".join(repr(marker) for marker in markers)
        message = f"RX idle {elapsed:.1f}s waiting for {marker_text} ({buffered} bytes buffered)"
        if self._serial_monitor:
            print(message, file=sys.stderr, flush=True)
        else:
            logger.debug(message)

    @property
    def progress_callback(
        self,
    ) -> Optional[Callable[[int, int], None]]:
        """Progress callback: (bytes_sent, total_bytes)."""
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(
        self, value: Optional[Callable[[int, int], None]]
    ) -> None:
        self._progress_callback = value

    def enter_bootloader(self) -> BootloaderResponse:
        """Enter bootloader mode.

        Some firmware builds accept ``AT+START`` from AT mode. The ROM/boot
        path used by the burn tool instead requires BOOT_SEL + reset and then
        echoes a ``>`` prompt. This method tries the AT command first, then
        falls back to synchronizing with that boot prompt.

        Returns:
            BootloaderResponse with mode detection.

        Raises:
            RuntimeError: If serial port is not open.
            TimeoutError: If bootloader mode is not entered within timeout.
        """
        logger.info("Sending AT+START to enter bootloader mode...")
        self._monitor_serial("TX", AT_START)
        self._serial.write(AT_START)

        try:
            raw = self._read_until_any(
                markers=(MARKER_BOOTLOADER_MODE, MARKER_ROM_CODE_MODE, MARKER_BOOT_PROMPT, b"\n"),
                timeout=self._boot_timeout,
                expected_length=4096,
            )
        except TimeoutError:
            logger.warning("No AT+START response; trying bootloader prompt sync")
            return self.sync_bootloader_prompt()

        resp = _parse_response(raw)
        if not resp.is_bootloader_mode and not resp.is_rom_code_mode:
            logger.warning(
                "Unexpected AT+START response, trying prompt sync: %s", resp.text
            )
            return self.sync_bootloader_prompt()

        logger.info(
            "Bootloader mode response: %s",
            "bootloader" if resp.is_bootloader_mode else "rom code",
        )

        return resp

    def sync_bootloader_prompt(self, timeout: float | None = None) -> BootloaderResponse:
        """Synchronize with a manually entered bootloader prompt.

        The Windows GUI/SDK flow sends Enter while the user or fixture resets
        the chip with BOOT_SEL asserted. A successful bootloader answers with
        the ``>`` prompt.
        """
        effective_timeout = timeout if timeout is not None else self._boot_timeout
        deadline = time.time() + effective_timeout
        raw = bytearray()

        logger.info("Waiting for bootloader prompt '>'...")
        while time.time() < deadline:
            enter = b"\r\n"
            self._monitor_serial("TX", enter)
            self._serial.write(enter)
            try:
                chunk = self._read_until_any(
                    markers=(MARKER_BOOTLOADER_MODE, MARKER_ROM_CODE_MODE, MARKER_BOOT_PROMPT),
                    timeout=min(0.5, max(0.05, deadline - time.time())),
                    expected_length=4096,
                )
            except TimeoutError:
                continue

            raw.extend(chunk)
            resp = _parse_response(bytes(raw))
            if resp.is_bootloader_mode or resp.is_rom_code_mode:
                logger.info(
                    "Synchronized with %s",
                    "bootloader prompt" if resp.is_bootloader_mode else "rom code mode",
                )
                return resp

        raise TimeoutError(
            "Timed out waiting for bootloader prompt '>'. "
            "Put the chip in bootloader mode with BOOT_SEL asserted and reset, then retry."
        )

    def send_firmware(
        self, data: bytes, addr: int = CODE1_ADDR
    ) -> BootloaderResponse:
        """Send firmware data to the chip via AT+SEND.

        The chip expects raw binary data after receiving AT+SEND.
        Data is sent in chunks for reliability.

        Args:
            data: Firmware binary data.
            addr: Target flash address (informational, not enforced by protocol).

        Returns:
            BootloaderResponse with success/failure status.

        Raises:
            RuntimeError: If serial port is not open.
            TimeoutError: If firmware send times out.
        """
        logger.info(
            "Sending %d bytes of firmware to addr 0x%06X...",
            len(data),
            addr,
        )

        # Send AT+SEND command first
        self._serial.write(AT_SEND)
        logger.debug("Sent AT+SEND command")

        # Send firmware data in chunks
        total_sent = 0
        num_chunks = (len(data) + self._chunk_size - 1) // self._chunk_size

        for i in range(0, len(data), self._chunk_size):
            chunk = data[i : i + self._chunk_size]
            self._serial.write(chunk)
            total_sent += len(chunk)

            if self._progress_callback:
                self._progress_callback(total_sent, len(data))

            logger.debug(
                "Sent chunk %d/%d (%d bytes)",
                i // self._chunk_size + 1,
                num_chunks,
                len(chunk),
            )

        # Wait for response
        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=self._send_timeout,
            expected_length=4096,
        )

        resp = _parse_response(raw)
        logger.info(
            "Firmware download result: %s",
            "SUCCESS" if resp.is_download_success else "FAIL",
        )

        return resp

    def reboot(self) -> BootloaderResponse:
        """Reboot the chip after firmware download.

        Returns:
            BootloaderResponse.

        Raises:
            RuntimeError: If serial port is not open.
        """
        logger.info("Sending AT+REBOOT...")
        self._serial.write(AT_REBOOT)

        # Give the chip time to reboot
        import time

        time.sleep(1)

        # Read any available response
        try:
            raw = self._serial.read_until(
                sentinel=b"\n",
                timeout=2.0,
                expected_length=256,
            )
            return _parse_response(raw)
        except TimeoutError:
            # Chip may have rebooted and stopped responding — that's OK
            logger.info("No response after reboot (chip may have restarted)")
            return BootloaderResponse(raw=b"", is_ok=True, text="Reboot sent")

    def send_bootloader(self, path: str) -> BootloaderResponse:
        """Send bootloader image to addr 0x000000.

        Args:
            path: Path to bootloader binary file.

        Returns:
            BootloaderResponse.

        Raises:
            FileNotFoundError: If bootloader file not found.
            ValueError: If bootloader exceeds max size (48 KB).
        """
        logger.info("Loading bootloader from %s", path)
        with open(path, "rb") as f:
            data = f.read()

        if len(data) > BOOTLOADER_MAX_SIZE:
            raise ValueError(
                f"Bootloader exceeds max size: {len(data)} > {BOOTLOADER_MAX_SIZE}"
            )

        logger.info(
            "Sending bootloader (%d bytes) to addr 0x%06X",
            len(data),
            BOOTLOADER_ADDR,
        )

        # Enter bootloader mode first
        resp = self.enter_bootloader()
        if not resp.is_bootloader_mode and not resp.is_rom_code_mode:
            logger.warning(
                "Bootloader mode not confirmed: %s", resp.text
            )

        return self.send_firmware(data, addr=BOOTLOADER_ADDR)

    def send_code1(self, path: str) -> BootloaderResponse:
        """Send CODE1 (ICCM firmware) to addr 0x010000.

        Args:
            path: Path to CODE1 binary file.

        Returns:
            BootloaderResponse.

        Raises:
            FileNotFoundError: If CODE1 file not found.
        """
        logger.info("Loading CODE1 from %s", path)
        with open(path, "rb") as f:
            data = f.read()

        logger.info(
            "Sending CODE1 (%d bytes) to addr 0x%06X",
            len(data),
            CODE1_ADDR,
        )
        return self.send_firmware(data, addr=CODE1_ADDR)

    def send_code2(self, path: str) -> BootloaderResponse:
        """Send CODE2 (Flash/AP firmware) to addr 0x040000.

        Args:
            path: Path to CODE2 binary file.

        Returns:
            BootloaderResponse.

        Raises:
            FileNotFoundError: If CODE2 file not found.
        """
        logger.info("Loading CODE2 from %s", path)
        with open(path, "rb") as f:
            data = f.read()

        logger.info(
            "Sending CODE2 (%d bytes) to addr 0x%06X",
            len(data),
            CODE2_ADDR,
        )
        return self.send_firmware(data, addr=CODE2_ADDR)

    def write_memory(self, address: int, value: int) -> BootloaderResponse:
        """Write a 32-bit value to memory via AT+wmem.

        Args:
            address: Memory address to write.
            value: 32-bit value to write.

        Returns:
            BootloaderResponse.

        Raises:
            RuntimeError: If serial port is not open.
            ValueError: If value is not a valid 32-bit integer.
        """
        if not (0 <= value <= 0xFFFFFFFF):
            raise ValueError(f"Value 0x{value:X} is not a 32-bit integer")

        cmd = f"AT+wmem {address:#010x} {value:#010x}\r\n".encode()
        logger.info("Writing 0x%08X to addr 0x%08X", value, address)
        self._serial.write(cmd)

        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=2.0,
            expected_length=256,
        )

        return _parse_response(raw)

    def read_memory(self, address: int, length: int = 4) -> BootloaderResponse:
        """Read bytes from memory via AT+WIFI_ETF_RMEM.

        Args:
            address: Memory address to read.
            length: Number of bytes to read (default: 4).

        Returns:
            BootloaderResponse with raw bytes.

        Raises:
            RuntimeError: If serial port is not open.
        """
        cmd = f"AT+WIFI_ETF_RMEM {address:08x} {length}\r\n".encode()
        logger.info("Reading %d bytes from addr 0x%08X", length, address)
        self._serial.write(cmd)

        # 6446/6447 response format:
        #   AT+WIFI_ETF_RMEM 00002000 4096
        #   System_timer_cancel:... (boot messages)
        #   {00000000: 00000000} 00000000 00000000 00000000{00000010: ...}
        #   +OK
        # Read until +OK marker (response is a long hex dump)
        raw = self._serial.read_until(
            sentinel=b"+OK",
            timeout=60.0,
            expected_length=length * 4 + 256,  # hex format: ~4 bytes per input byte
        )

        logger.debug("Received %d bytes from AT+WIFI_ETF_RMEM", len(raw))

        # Parse hex blocks: {addr: data} data data ...
        parsed = _parse_hex_memory_response(raw, length, base_address=address)
        resp = _parse_response(raw)
        resp.raw = parsed  # Replace raw with parsed bytes
        return resp

    def _read_until_any(
        self,
        markers: tuple[bytes, ...],
        timeout: float,
        expected_length: int,
    ) -> bytes:
        """Read until any marker appears, or until timeout/size limit."""
        start_time = time.time()
        last_idle_report = start_time
        result = bytearray()

        while True:
            now = time.time()
            if now - start_time > timeout:
                raise TimeoutError(f"Timeout waiting for any of {markers!r}")
            if len(result) > expected_length:
                raise TimeoutError(
                    f"Read more than {expected_length} bytes without finding any of {markers!r}"
                )

            remaining = max(0.05, timeout - (time.time() - start_time))
            chunk = self._serial.read(length=256, timeout=min(0.1, remaining))
            if not chunk:
                now = time.time()
                if now - last_idle_report >= 5.0:
                    self._monitor_idle(now - start_time, markers, len(result))
                    last_idle_report = now
                time.sleep(0.01)
                continue

            self._monitor_serial("RX", chunk)
            result.extend(chunk)
            if any(marker in result for marker in markers):
                return bytes(result)

    def _reset_input_buffer(self) -> None:
        reset = getattr(self._serial, "reset_input_buffer", None)
        if callable(reset):
            reset()

    def read_flash(self, offset: int, length: int = 4) -> BootloaderResponse:
        """Read bytes from SPI flash through bootloader memory mapping.

        The SDK maps flash offset 0 to memory address 0x00400000 in bootloader
        context. This keeps the public API in flash offsets while avoiding RAM
        address 0 reads.
        """
        if offset < 0:
            raise ValueError("Flash offset must be non-negative")
        if length <= 0:
            return BootloaderResponse(raw=b"", is_ok=True, text="")

        address = FLASH_MEMORY_BASE + offset
        dword_count = (length + 3) // 4
        commands = (
            f"rmem {address:08x} {dword_count}\r\n".encode(),
            f"AT+rmem {address:08x} {dword_count}\r\n".encode(),
            f"AT+WIFI_ETF_RMEM {address:08x} {length}\r\n".encode(),
        )
        last_raw = b""

        for cmd in commands:
            logger.info("Reading %d flash bytes at offset 0x%06X via %r", length, offset, cmd.strip())
            self._reset_input_buffer()
            self._monitor_serial("TX", cmd)
            self._serial.write(cmd)
            raw = self._read_until_any(
                markers=(MARKER_BOOT_PROMPT, b"+OK", b"\nOK", b"+ERR", b"ERROR", b"Unknown command"),
                timeout=60.0,
                expected_length=max(length * 8 + 4096, 8192),
            )
            last_raw = raw

            if b"+ERR" in raw or b"ERROR" in raw or b"Unknown command" in raw:
                logger.debug("Flash read command rejected: %r", raw[-256:])
                continue

            try:
                parsed = _parse_hex_memory_response(raw, length, base_address=address)
            except ValueError:
                logger.debug("Flash read command produced no parseable data: %r", raw[-256:])
                continue
            resp = _parse_response(raw)
            resp.raw = parsed
            return resp

        resp = _parse_response(last_raw)
        raise RuntimeError(f"Flash read command rejected by device: {resp.text}")

    def get_modem_info(self) -> BootloaderResponse:
        """Get modem info via AT+GMR.

        Returns:
            BootloaderResponse with modem information.
        """
        logger.info("Sending AT+GMR...")
        self._serial.write(AT_GMR)

        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=2.0,
            expected_length=512,
        )

        return _parse_response(raw)

    def get_sdk_version(self) -> BootloaderResponse:
        """Get SDK version via AT+GET_SDK_VER.

        Returns:
            BootloaderResponse with SDK version.
        """
        logger.info("Sending AT+GET_SDK_VER...")
        self._serial.write(AT_GET_SDK_VER)

        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=2.0,
            expected_length=256,
        )

        return _parse_response(raw)

    def get_hw_version(self) -> BootloaderResponse:
        """Get hardware version via AT+VENVER.

        Returns:
            BootloaderResponse with hardware version.
        """
        logger.info("Sending AT+VENVER...")
        self._serial.write(AT_VENVER)

        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=2.0,
            expected_length=256,
        )

        return _parse_response(raw)

    def get_fw_info(self) -> BootloaderResponse:
        """Get firmware info via AT+WIFI_GET_FWINFO.

        Returns:
            BootloaderResponse with firmware information.
        """
        logger.info("Sending AT+WIFI_GET_FWINFO...")
        self._serial.write(AT_WIFI_GET_FWINFO)

        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=2.0,
            expected_length=256,
        )

        return _parse_response(raw)

    def get_wifi_status(self) -> BootloaderResponse:
        """Get WiFi status via AT+WIFI_STATUS.

        Returns:
            BootloaderResponse with WiFi status.
        """
        logger.info("Sending AT+WIFI_STATUS...")
        self._serial.write(AT_WIFI_STATUS)

        raw = self._serial.read_until(
            sentinel=b"\n",
            timeout=2.0,
            expected_length=256,
        )

        return _parse_response(raw)

    def burn_firmware(self, spec: FirmwareSpec) -> BootloaderResponse:
        """Burn all specified firmware images in sequence.

        Order: bootloader → KEY → CODE1 → CODE2 → reboot

        Args:
            spec: Firmware specification.

        Returns:
            BootloaderResponse with final status.

        Raises:
            FileNotFoundError: If any firmware file not found.
        """
        logger.info("=== Starting firmware burn ===")
        logger.info(
            "  bootloader: %s", spec.bootloader or "N/A"
        )
        logger.info("  code1: %s", spec.code1 or "N/A")
        logger.info("  code2: %s", spec.code2 or "N/A")
        logger.info("  keyfile: %s", spec.keyfile or "N/A")

        results: list[BootloaderResponse] = []

        # 1. Bootloader
        if spec.bootloader:
            logger.info("--- Step 1: Bootloader ---")
            resp = self.send_bootloader(spec.bootloader)
            results.append(resp)
            if not resp.is_download_success:
                logger.error("Bootloader download failed: %s", resp.text)
                return resp

        # 2. KEY data (if keyfile specified)
        if spec.keyfile:
            logger.info("--- Step 2: KEY data ---")
            resp = self._burn_key(spec)
            results.append(resp)
            if resp.is_error or resp.is_download_fail:
                logger.error("KEY burn failed: %s", resp.text)
                return resp

        # 3. CODE1 (ICCM)
        if spec.code1:
            logger.info("--- Step 3: CODE1 (ICCM) ---")
            resp = self.send_code1(spec.code1)
            results.append(resp)
            if not resp.is_download_success:
                logger.error("CODE1 download failed: %s", resp.text)
                return resp

        # 4. CODE2 (Flash)
        if spec.code2:
            logger.info("--- Step 4: CODE2 (Flash) ---")
            resp = self.send_code2(spec.code2)
            results.append(resp)
            if not resp.is_download_success:
                logger.error("CODE2 download failed: %s", resp.text)
                return resp

        # 5. Reboot
        logger.info("--- Step 5: Reboot ---")
        resp = self.reboot()
        results.append(resp)

        logger.info("=== Firmware burn complete ===")
        return resp

    def _burn_key(self, spec: FirmwareSpec) -> BootloaderResponse:
        """Burn KEY data from file.

        KEY file is typically CSV format with key values.
        Each key is written as a 32-bit value to key1_addr and key2_addr.

        Args:
            spec: Firmware specification with keyfile path.

        Returns:
            BootloaderResponse.
        """
        logger.info("Loading KEY data from %s", spec.keyfile)
        with open(spec.keyfile, "r") as f:
            content = f.read().strip()

        # KEY file is typically a 32-byte hex string (64 hex chars)
        # or CSV with key columns
        if content.startswith("key") or "," in content:
            # CSV format — extract key values
            import csv

            reader = csv.reader(content.splitlines())
            keys = []
            for row in reader:
                for val in row:
                    val = val.strip()
                    if val and val.lower() != "key":
                        keys.append(val)
        else:
            # Plain hex string
            keys = [content]

        if not keys:
            logger.warning("No KEY data found in file")
            return BootloaderResponse(
                raw=b"", is_ok=True, text="No KEY data"
            )

        # Write keys to memory
        results: list[BootloaderResponse] = []
        for i, key_str in enumerate(keys):
            try:
                # Parse hex key (may be 32 bytes = 64 hex chars)
                key_bytes = bytes.fromhex(key_str.replace(" ", ""))
            except ValueError:
                logger.warning("Invalid key format: %s, skipping", key_str)
                continue

            # Split into 4-byte chunks and write to memory
            for j in range(0, len(key_bytes), 4):
                chunk = key_bytes[j : j + 4]
                if len(chunk) == 4:
                    value = struct.unpack(">I", chunk)[0]
                    # Distribute across key1_addr and key2_addr
                    addr = (
                        spec.key1_addr + j
                        if j < spec.key2_addr - spec.key1_addr
                        else spec.key2_addr + (j - (spec.key2_addr - spec.key1_addr))
                    )
                    resp = self.write_memory(addr, value)
                    results.append(resp)
                    if resp.is_error:
                        logger.error(
                            "KEY write failed at 0x%08X: %s", addr, resp.text
                        )
                        return resp

        if not results:
            return BootloaderResponse(
                raw=b"", is_ok=True, text="KEY burn skipped (no valid data)"
            )

        last = results[-1]
        return BootloaderResponse(
            raw=b"",
            is_ok=True,
            text=f"KEY burned: {len(results)} writes",
        )

    def close(self) -> None:
        """Close the serial connection."""
        self._serial.close()

    def __enter__(self) -> BootloaderProtocol:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Context manager exit."""
        self.close()
