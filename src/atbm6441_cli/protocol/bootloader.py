"""ATBM6441 bootloader protocol — AT command interface for firmware download.

Protocol discovered from Altobem WIFI IOT GUI V1.0.52:

1. Open UART at 1,000,000 baud (24MHz crystal) or 1,500,000 (16MHz)
2. Send ``AT+START\r\n`` → chip enters bootloader mode
3. Wait for ``[ bootloader mode ]`` response
4. Send ``AT+SEND\r\n`` → chip expects firmware data
5. Send firmware data in raw binary chunks
6. Wait for ``<<<   download SUCCESS   >>>`` or ``download fail``
7. Send ``AT+REBOOT\r\n`` → chip reboots with new firmware

When the chip is already at the raw bootloader ``>`` prompt, the prompt does
not accept AT commands. In that mode firmware is sent with ``fwupdata`` and
binary ``download_s`` packets.

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
BOOTLOADER_RMEM_PAGE_SIZE = 256

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

BOOT_FWUPDATA = b"fwupdata"
BOOT_BOOT = b"boot\r\n"

FWUPDATA_CHUNK_SIZE = 4096
FWUPDATA_PACKET_SIZE = 4108
FWUPDATA_HEADER_SIZE = 12
FWUPDATA_MODE_SWITCH_TIMEOUT = 3.0
FWUPDATA_DEFAULT_MSG_ID = 0
FWUPDATA_CODE1_TYPE = 1
FWUPDATA_CODE2_TYPE = 2
FWUPDATA_FLAGS_DATA = 0
FWUPDATA_FLAGS_LAST = 1
FWUPDATA_CHECKSUM_MODES = ("sum-bytes", "sum-words", "firmware-bytes")
FWUPDATA_RESULT_NAMES = {
    0: "DOWNLOAD_SUCCESS",
    1: "DOWNLOAD_ERR_BAD_WR",
    2: "DOWNLOAD_ERR_BAD_TYPE",
    3: "DOWNLOAD_ERR_BAD_OFFSET",
    4: "DOWNLOAD_ERR_BAD_OP",
    5: "DOWNLOAD_ERR_FILE_SIZE",
    6: "DOWNLOAD_ERR_CHECKSUM",
    7: "DOWNLOAD_ERR_DECODE",
}

# ── Response markers ─────────────────────────────────────────────────────

MARKER_BOOTLOADER_MODE = b"[ bootloader mode ]"
MARKER_ROM_CODE_MODE = b"[ rom code mode ]"
MARKER_BOOT_PROMPT = b">"
MARKER_DOWNLOAD_SUCCESS = b"download SUCCESS"
MARKER_DOWNLOAD_FAIL = b"download fail"
MARKER_FWUPDATA_MODE_V2 = b"change Msg mode v2"
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


@dataclass
class FwupdataOptions:
    """Raw bootloader fwupdata protocol options."""

    msg_id: int = FWUPDATA_DEFAULT_MSG_ID
    code1_type: int = FWUPDATA_CODE1_TYPE
    code2_type: int = FWUPDATA_CODE2_TYPE
    normal_flags: int = FWUPDATA_FLAGS_DATA
    last_flags: int = FWUPDATA_FLAGS_LAST
    checksum: str = "sum-bytes"
    packet_delay_ms: int = 0


@dataclass
class FwupdataAck:
    """Binary ``boot_ind_s`` acknowledgement from fwupdata mode."""

    msg_len: int
    msg_id: int
    offset: int
    state: int
    result: int
    raw: bytes = field(repr=False)


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


def _sum16_words(data: bytes) -> int:
    """Return a 16-bit little-endian word sum, padding odd inputs with zero."""
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += data[i] | (data[i + 1] << 8)
    return total & 0xFFFF


def _fwupdata_checksum(packet: bytearray, chunk_length: int, mode: str) -> int:
    """Compute the fwupdata ``download_s.checksum`` field."""
    if mode not in FWUPDATA_CHECKSUM_MODES:
        raise ValueError(f"Unsupported fwupdata checksum mode: {mode}")

    if mode == "firmware-bytes":
        return sum(packet[FWUPDATA_HEADER_SIZE : FWUPDATA_HEADER_SIZE + chunk_length]) & 0xFFFF

    data = bytes(packet[:10]) + bytes(packet[FWUPDATA_HEADER_SIZE:])
    if mode == "sum-words":
        return _sum16_words(data)
    return sum(data) & 0xFFFF


def _build_fwupdata_packet(
    chunk: bytes,
    *,
    offset: int,
    fw_type: int,
    flags: int,
    msg_id: int = FWUPDATA_DEFAULT_MSG_ID,
    checksum: str = "sum-bytes",
) -> bytes:
    """Build a raw bootloader ``download_s`` packet.

    SDK PDB symbols define the packet as:

        uint16_t MsgLen;
        uint16_t MsgId;
        uint32_t Offset;
        uint8_t Flags;
        uint8_t FwType;
        uint16_t checksum;
        uint8_t Firmware[4096];

    ``MsgLen`` is the number of valid firmware bytes in this packet.
    """
    if len(chunk) > FWUPDATA_CHUNK_SIZE:
        raise ValueError(
            f"fwupdata chunk too large: {len(chunk)} > {FWUPDATA_CHUNK_SIZE}"
        )
    if not (0 <= offset <= 0xFFFFFFFF):
        raise ValueError(f"fwupdata offset out of range: 0x{offset:X}")
    if not (0 <= msg_id <= 0xFFFF):
        raise ValueError(f"fwupdata MsgId out of range: 0x{msg_id:X}")
    if not (0 <= flags <= 0xFF):
        raise ValueError(f"fwupdata Flags out of range: 0x{flags:X}")
    if not (0 <= fw_type <= 0xFF):
        raise ValueError(f"fwupdata FwType out of range: 0x{fw_type:X}")

    packet = bytearray(FWUPDATA_PACKET_SIZE)
    struct.pack_into(
        "<HHIBB",
        packet,
        0,
        len(chunk),
        msg_id,
        offset,
        flags,
        fw_type,
    )
    packet[FWUPDATA_HEADER_SIZE : FWUPDATA_HEADER_SIZE + len(chunk)] = chunk
    struct.pack_into("<H", packet, 10, _fwupdata_checksum(packet, len(chunk), checksum))
    return bytes(packet)


def _parse_fwupdata_ack(raw: bytes) -> FwupdataAck:
    """Parse a raw ``boot_ind_s`` acknowledgement."""
    if len(raw) < 16:
        raise ValueError(f"fwupdata ack too short: {len(raw)} bytes")
    msg_len, msg_id, offset, state, result = struct.unpack("<HHIII", raw[:16])
    return FwupdataAck(
        msg_len=msg_len,
        msg_id=msg_id,
        offset=offset,
        state=state,
        result=result,
        raw=raw[:16],
    )


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
    parsed, parsed_count = _parse_hex_memory_response_with_count(
        raw,
        expected_length,
        base_address=base_address,
    )
    if parsed_count == 0 and expected_length:
        raise ValueError("No hex memory data found in response")

    return parsed


def _parse_hex_memory_response_with_count(
    raw: bytes,
    expected_length: int,
    base_address: int | None = None,
) -> tuple[bytes, int]:
    """Parse a memory dump and return parsed bytes plus unique byte count."""
    import re
    text = raw.decode("utf-8", errors="replace")

    result = bytearray(expected_length)
    parsed_positions: set[int] = set()

    def write_word(addr: int, word: str) -> None:
        if base_address is not None and addr >= base_address:
            addr -= base_address
        word_bytes = bytes.fromhex(word)[::-1]
        for byte_idx in range(4):
            pos = addr + byte_idx
            if 0 <= pos < expected_length:
                result[pos] = word_bytes[byte_idx]
                parsed_positions.add(pos)

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

    return bytes(result), len(parsed_positions)


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
        flash_base: int = FLASH_MEMORY_BASE,
    ) -> None:
        """Initialize the bootloader protocol.

        Args:
            serial: Open SerialManager instance.
            chunk_size: Data chunk size for firmware transfer (default: 1024).
            send_timeout: Timeout for firmware send operation (seconds).
            boot_timeout: Timeout for bootloader mode entry (seconds).
            serial_monitor: Mirror bootloader TX/RX chunks to stderr.
            flash_base: Memory-mapped flash base address for bootloader rmem.
        """
        self._serial = serial
        self._chunk_size = chunk_size
        self._send_timeout = send_timeout
        self._boot_timeout = boot_timeout
        self._serial_monitor = serial_monitor
        self._flash_base = flash_base
        self._progress_callback: Optional[Callable[[int, int], None]] = None

    def _monitor_serial(self, direction: str, data: bytes) -> None:
        message = f"{direction} {_format_serial_bytes(data)}"
        if self._serial_monitor:
            arrow = ">>" if direction == "TX" else "<<"
            text = data.decode("utf-8", errors="replace")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            lines = text.split("\n")
            if lines and lines[-1] == "":
                lines = lines[:-1]
            for line in lines or [""]:
                print(f"[{direction}] {arrow} {line}", file=sys.stderr, flush=True)
        else:
            logger.debug(message)

    def _monitor_binary(self, direction: str, data: bytes, label: str) -> None:
        message = f"{direction} {label}: {_format_serial_bytes(data, limit=48)}"
        if self._serial_monitor:
            arrow = ">>" if direction == "TX" else "<<"
            print(f"[{direction}] {arrow} {label}: {_format_serial_bytes(data, limit=48)}", file=sys.stderr, flush=True)
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

        self._reset_input_buffer()

        # Send AT+SEND command first
        self._monitor_serial("TX", AT_SEND)
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

        raw = self._read_firmware_download_response(payload_length=len(data))

        resp = _parse_response(raw)
        logger.info(
            "Firmware download result: %s",
            "SUCCESS" if resp.is_download_success else "FAIL",
        )

        return resp

    def _read_firmware_download_response(self, payload_length: int) -> bytes:
        """Read the bootloader's response after a raw firmware transfer."""
        terminal_markers = (
            MARKER_DOWNLOAD_SUCCESS,
            MARKER_DOWNLOAD_FAIL,
            b"OK\r\n",
            b"OK\n",
            b"+OK",
            MARKER_ERROR,
        )
        max_length = max(payload_length + 64 * 1024, 64 * 1024)
        start_time = time.time()
        last_idle_report = start_time
        result = bytearray()

        while True:
            now = time.time()
            if now - start_time > self._send_timeout:
                raise TimeoutError(
                    f"Timeout waiting for firmware download response after {len(result)} bytes"
                )
            if len(result) > max_length:
                raise TimeoutError(
                    f"Read more than {max_length} bytes without finding a firmware download response"
                )

            remaining = max(0.05, self._send_timeout - (time.time() - start_time))
            chunk = self._serial.read(length=256, timeout=min(0.1, remaining))
            if not chunk:
                now = time.time()
                if now - last_idle_report >= 5.0:
                    self._monitor_idle(now - start_time, terminal_markers, len(result))
                    last_idle_report = now
                time.sleep(0.01)
                continue

            self._monitor_serial("RX", chunk)
            result.extend(chunk)
            if any(marker in result for marker in terminal_markers):
                return bytes(result)

    def _read_exact(self, length: int, timeout: float, label: str) -> bytes:
        """Read an exact number of bytes from the serial stream."""
        start_time = time.time()
        last_idle_report = start_time
        result = bytearray()

        while len(result) < length:
            now = time.time()
            if now - start_time > timeout:
                partial = bytes(result)
                raise TimeoutError(
                    f"Timeout waiting for {label}: got {len(result)}/{length} bytes; "
                    f"partial={_format_serial_bytes(partial, limit=128)}"
                )

            remaining = length - len(result)
            chunk = self._serial.read(length=remaining, timeout=min(0.1, timeout))
            if not chunk:
                now = time.time()
                if now - last_idle_report >= 5.0:
                    self._monitor_idle(now - start_time, (label.encode(),), len(result))
                    last_idle_report = now
                time.sleep(0.01)
                continue

            self._monitor_binary("RX", chunk, f"{label} partial")
            result.extend(chunk)

        return bytes(result[:length])

    def send_fwupdata_file(
        self,
        data: bytes,
        *,
        fw_type: int,
        label: str,
        options: FwupdataOptions | None = None,
    ) -> BootloaderResponse:
        """Send one firmware image through the raw bootloader ``fwupdata`` mode.

        This is the mode reached from the interactive ``>`` prompt. The prompt
        prints ``change Msg mode v2`` and then consumes binary ``download_s``
        packets rather than AT commands.
        """
        if options is None:
            options = FwupdataOptions()
        if options.checksum not in FWUPDATA_CHECKSUM_MODES:
            raise ValueError(f"Unsupported fwupdata checksum mode: {options.checksum}")
        if options.packet_delay_ms < 0:
            raise ValueError("fwupdata packet delay must be non-negative")

        logger.info(
            "Sending %s (%d bytes) via fwupdata type %d",
            label,
            len(data),
            fw_type,
        )

        self._reset_input_buffer()
        raw = b""
        cmd = BOOT_FWUPDATA + b"\n"
        self._monitor_serial("TX", cmd)
        self._serial.write(cmd)

        try:
            raw = self._read_until_any(
                markers=(
                    MARKER_FWUPDATA_MODE_V2,
                    b"Unknown command",
                    b"+ERR",
                    MARKER_ERROR,
                ),
                timeout=min(self._boot_timeout, FWUPDATA_MODE_SWITCH_TIMEOUT),
                expected_length=4096,
            )
        except TimeoutError:
            logger.warning(
                "No fwupdata mode banner; assuming bootloader entered binary message mode"
            )
        else:
            if (
                b"Unknown command" in raw
                or b"+ERR" in raw
                or MARKER_ERROR in raw
            ):
                resp = _parse_response(raw)
                raise RuntimeError(f"Bootloader rejected fwupdata command: {resp.text}")

        total_sent = 0
        last_ack: FwupdataAck | None = None
        chunk_size = FWUPDATA_CHUNK_SIZE
        total_chunks = (len(data) + chunk_size - 1) // chunk_size

        for index, offset in enumerate(range(0, len(data), chunk_size), start=1):
            chunk = data[offset : offset + chunk_size]
            is_last = offset + len(chunk) >= len(data)
            flags = options.last_flags if is_last else options.normal_flags
            packet = _build_fwupdata_packet(
                chunk,
                offset=offset,
                fw_type=fw_type,
                flags=flags,
                msg_id=options.msg_id,
                checksum=options.checksum,
            )
            checksum_value = struct.unpack_from("<H", packet, 10)[0]
            logger.debug(
                "Sending %s fwupdata chunk %d/%d offset=0x%06X len=%d "
                "flags=0x%02X checksum=0x%04X",
                label,
                index,
                total_chunks,
                offset,
                len(chunk),
                flags,
                checksum_value,
            )
            self._monitor_binary(
                "TX",
                packet,
                (
                    f"{label} packet offset=0x{offset:06X} len={len(chunk)} "
                    f"flags=0x{flags:02X} csum=0x{checksum_value:04X}"
                ),
            )
            self._serial.write(packet)

            ack_raw = self._read_exact(16, timeout=self._send_timeout, label="fwupdata ack")
            self._monitor_binary("RX", ack_raw, f"{label} ack offset=0x{offset:06X}")
            ack = _parse_fwupdata_ack(ack_raw)
            last_ack = ack
            if ack.result != 0:
                result_name = FWUPDATA_RESULT_NAMES.get(ack.result, f"result {ack.result}")
                raise RuntimeError(
                    f"{label} fwupdata failed at offset 0x{offset:06X}: "
                    f"state={ack.state} result={ack.result} ({result_name})"
                )

            total_sent += len(chunk)
            if self._progress_callback:
                self._progress_callback(total_sent, len(data))
            if options.packet_delay_ms and not is_last:
                time.sleep(options.packet_delay_ms / 1000.0)

        raw_ack = last_ack.raw if last_ack is not None else raw
        return BootloaderResponse(
            raw=raw_ack,
            is_ok=True,
            is_download_success=True,
            text=f"{label} fwupdata complete",
        )

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

    def send_code1_fwupdata(
        self,
        path: str,
        options: FwupdataOptions | None = None,
    ) -> BootloaderResponse:
        """Send CODE1 through the raw bootloader ``fwupdata`` protocol."""
        if options is None:
            options = FwupdataOptions()
        logger.info("Loading CODE1 from %s", path)
        with open(path, "rb") as f:
            data = f.read()
        return self.send_fwupdata_file(
            data,
            fw_type=options.code1_type,
            label="CODE1",
            options=options,
        )

    def send_code2_fwupdata(
        self,
        path: str,
        options: FwupdataOptions | None = None,
    ) -> BootloaderResponse:
        """Send CODE2 through the raw bootloader ``fwupdata`` protocol."""
        if options is None:
            options = FwupdataOptions()
        logger.info("Loading CODE2 from %s", path)
        with open(path, "rb") as f:
            data = f.read()
        return self.send_fwupdata_file(
            data,
            fw_type=options.code2_type,
            label="CODE2",
            options=options,
        )

    def boot_from_prompt(self) -> BootloaderResponse:
        """Run the raw bootloader ``boot`` command."""
        logger.info("Sending boot command from raw bootloader prompt...")
        self._monitor_serial("TX", BOOT_BOOT)
        self._serial.write(BOOT_BOOT)
        try:
            raw = self._read_until_any(
                markers=(
                    MARKER_BOOTLOADER_MODE,
                    MARKER_ROM_CODE_MODE,
                    MARKER_BOOT_PROMPT,
                    MARKER_OK,
                    MARKER_ERROR,
                ),
                timeout=2.0,
                expected_length=4096,
            )
            resp = _parse_response(raw)
            if not resp.is_error:
                resp.is_ok = True
            return resp
        except TimeoutError:
            logger.info("No response after boot command (chip may have started firmware)")
            return BootloaderResponse(raw=b"", is_ok=True, text="boot sent")

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

    def _read_bootloader_rmem_page(self, address: int, length: int) -> bytes:
        """Read one fixed bootloader rmem page using ``rmem <addr>``."""
        cmd = f"rmem {address:x}\r\n".encode()
        logger.info("Reading bootloader rmem page at 0x%08X via %r", address, cmd.strip())
        self._reset_input_buffer()
        self._monitor_serial("TX", cmd)
        self._serial.write(cmd)

        start_time = time.time()
        last_idle_report = start_time
        parsed: bytes | None = None
        parsed_at = 0.0
        result = bytearray()
        expected_text_length = max(length * 16 + 2048, 4096)
        terminal_markers = (b"\r\n>", b"\n>", b"\r>", b"+OK", b"\nOK")
        error_markers = (b"+ERR", b"ERROR", b"Unknown command")

        while True:
            now = time.time()
            if now - start_time > 10.0:
                if parsed is not None:
                    return parsed
                raise TimeoutError(f"Timeout waiting for rmem page at 0x{address:08X}")
            if len(result) > expected_text_length:
                raise TimeoutError(
                    f"Read more than {expected_text_length} bytes without completing rmem page"
                )

            chunk = self._serial.read(length=256, timeout=0.1)
            if not chunk:
                now = time.time()
                if parsed is not None and now - parsed_at >= 0.25:
                    return parsed
                if now - last_idle_report >= 5.0:
                    self._monitor_idle(now - start_time, terminal_markers, len(result))
                    last_idle_report = now
                time.sleep(0.01)
                continue

            self._monitor_serial("RX", chunk)
            result.extend(chunk)
            raw = bytes(result)

            if any(marker in raw for marker in error_markers):
                resp = _parse_response(raw)
                raise RuntimeError(f"Bootloader rmem rejected command: {resp.text}")

            candidate, parsed_count = _parse_hex_memory_response_with_count(
                raw,
                length,
                base_address=address,
            )
            if parsed_count >= length:
                parsed = candidate
                parsed_at = time.time()

            if parsed is not None and any(marker in raw for marker in terminal_markers):
                return parsed

    def _read_flash_legacy(self, offset: int, length: int) -> BootloaderResponse:
        """Fallback flash reads for app/AT command modes."""
        address = self._flash_base + offset
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
                markers=(b"\r\n>", b"\n>", b"+OK", b"\nOK", b"+ERR", b"ERROR", b"Unknown command"),
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

    def read_flash(self, offset: int, length: int = 4) -> BootloaderResponse:
        """Read bytes from SPI flash through bootloader memory mapping.

        The bootloader prompt command observed on hardware is ``rmem <addr>``
        and returns a fixed memory dump page. This keeps the public API in
        flash offsets while reading enough pages to satisfy the requested byte
        length.
        """
        if offset < 0:
            raise ValueError("Flash offset must be non-negative")
        if length <= 0:
            return BootloaderResponse(raw=b"", is_ok=True, text="")

        result = bytearray()
        while len(result) < length:
            page_offset = offset + len(result)
            page_length = min(BOOTLOADER_RMEM_PAGE_SIZE, length - len(result))
            address = self._flash_base + page_offset
            try:
                page = self._read_bootloader_rmem_page(address, page_length)
            except (RuntimeError, TimeoutError, ValueError) as e:
                if result:
                    raise
                logger.debug("Bootloader rmem page read failed, trying legacy commands: %s", e)
                return self._read_flash_legacy(offset, length)
            result.extend(page[:page_length])

        return BootloaderResponse(raw=bytes(result), is_ok=True, text="")

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

    def burn_firmware(self, spec: FirmwareSpec, reboot: bool = True) -> BootloaderResponse:
        """Burn all specified firmware images in sequence.

        Order: bootloader → KEY → CODE1 → CODE2 → reboot

        Args:
            spec: Firmware specification.
            reboot: Send AT+REBOOT after all images are downloaded.

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

        if not reboot:
            logger.info("Skipping reboot after firmware burn")
            return results[-1] if results else BootloaderResponse(
                raw=b"",
                is_ok=True,
                text="No firmware images specified",
            )

        # 5. Reboot
        logger.info("--- Step 5: Reboot ---")
        resp = self.reboot()
        results.append(resp)

        logger.info("=== Firmware burn complete ===")
        return resp

    def burn_firmware_fwupdata(
        self,
        spec: FirmwareSpec,
        reboot: bool = True,
        options: FwupdataOptions | None = None,
    ) -> BootloaderResponse:
        """Burn CODE1/CODE2 from the raw bootloader ``fwupdata`` prompt."""
        if options is None:
            options = FwupdataOptions()

        if spec.bootloader:
            raise ValueError(
                "Raw fwupdata manual mode does not support --bootloader yet"
            )
        if spec.keyfile or spec.mac:
            raise ValueError(
                "Raw fwupdata manual mode supports CODE1/CODE2 only; "
                "omit --keyfile/--mac"
            )

        logger.info("=== Starting raw fwupdata firmware burn ===")
        logger.info("  code1: %s", spec.code1 or "N/A")
        logger.info("  code2: %s", spec.code2 or "N/A")
        logger.info(
            "  fwupdata options: msg_id=0x%04X code1_type=%d code2_type=%d "
            "flags=0x%02X/0x%02X checksum=%s",
            options.msg_id,
            options.code1_type,
            options.code2_type,
            options.normal_flags,
            options.last_flags,
            options.checksum,
        )

        results: list[BootloaderResponse] = []

        if spec.code1:
            logger.info("--- Step 1: CODE1 (ICCM) fwupdata ---")
            resp = self.send_code1_fwupdata(spec.code1, options=options)
            results.append(resp)

        if spec.code2:
            logger.info("--- Step 2: CODE2 (Flash) fwupdata ---")
            resp = self.send_code2_fwupdata(spec.code2, options=options)
            results.append(resp)

        if not results:
            return BootloaderResponse(
                raw=b"",
                is_ok=True,
                text="No CODE1/CODE2 images specified",
            )

        if not reboot:
            logger.info("Skipping boot command after raw fwupdata burn")
            return results[-1]

        logger.info("--- Step 3: Boot ---")
        resp = self.boot_from_prompt()
        results.append(resp)
        logger.info("=== Raw fwupdata firmware burn complete ===")
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
