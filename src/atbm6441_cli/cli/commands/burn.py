"""burn command — Flash firmware images to the ATBM6441 chip via UART.

Protocol flow (from Altobem WIFI IOT GUI):
    1. Open UART at 1,000,000 baud
    2. Send ``AT+START\r\n`` → enter bootloader mode
    3. Send ``AT+SEND\r\n`` → chip expects firmware data
    4. Send firmware binary in chunks
    5. Wait for ``<<< download SUCCESS >>>``
    6. Send ``AT+REBOOT\r\n`` → execute firmware
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from ...protocol.bootloader import (
    BootloaderProtocol,
    FirmwareSpec,
    BootloaderResponse,
    BOOTLOADER_ADDR,
    CODE1_ADDR,
    CODE2_ADDR,
)
from ...protocol.uart import SerialManager

logger = logging.getLogger(__name__)


def burn_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the burn subcommand parser."""
    p = subparsers.add_parser(
        "burn",
        help="Flash firmware images to the ATBM6441 chip via UART",
    )
    p.add_argument(
        "--port", "-p", default=None, help="Serial port (e.g. /dev/ttyUSB0)"
    )
    p.add_argument(
        "--auto-detect",
        action="store_true",
        help="Auto-detect FT232 serial port",
    )
    p.add_argument(
        "--baud",
        "-b",
        default=1000000,
        type=int,
        help="Burn baud rate (default: 1000000)",
    )
    p.add_argument(
        "--at-baud",
        default=115200,
        type=int,
        help="AT command baud rate (default: 115200)",
    )
    p.add_argument(
        "--boot-timeout",
        default=5,
        type=int,
        help="Seconds to wait for bootloader prompt",
    )
    p.add_argument(
        "--firmware",
        "-f",
        type=str,
        help="Path to firmware image (CODE1: fw_update1.bin)",
    )
    p.add_argument(
        "--bootloader",
        "-F",
        type=str,
        help="Path to bootloader image (bootloader_step1.bin)",
    )
    p.add_argument(
        "--flashcode",
        type=str,
        help="Path to flash code image (fw_update2.bin)",
    )
    p.add_argument(
        "--keyfile", type=str, help="Path to KEY file (CSV/TXT)"
    )
    p.add_argument(
        "--mac", type=str, help="MAC address to burn (aa:bb:cc:dd:ee:ff)"
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Force destructive operations",
    )
    p.add_argument(
        "--manual-mode",
        action="store_true",
        help="Skip auto GPIO control; user handles reset manually",
    )
    p.add_argument(
        "--no-reboot",
        action="store_true",
        help="Do not send AT+REBOOT after downloading firmware",
    )
    p.add_argument(
        "--serial-monitor",
        action="store_true",
        help="Mirror bootloader TX/RX bytes to stderr",
    )
    p.add_argument(
        "--no-flash-protect",
        action="store_true",
        help="Disable flash write protection before burn",
    )
    p.add_argument(
        "--flash-addr",
        type=str,
        help="Override default flash burn address (e.g. 0x100000)",
    )
    p.add_argument(
        "--log-level",
        "-l",
        default="info",
        choices=["debug", "info", "warn", "error"],
        help="Log level",
    )
    p.add_argument(
        "--json", action="store_true", help="JSON output mode"
    )
    p.set_defaults(handler=burn_handler)


def burn_handler(args: argparse.Namespace) -> int:
    """Handle the burn command.

    Protocol flow:
        1. Open UART at 1,000,000 baud
        2. Send AT+START → enter bootloader mode
        3. Send AT+SEND → expect firmware data
        4. Send firmware binary in chunks
        5. Wait for download SUCCESS
        6. Send AT+REBOOT → execute firmware
    """
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Resolve file paths
    firmware_path = Path(args.firmware) if args.firmware else None
    bootloader_path = Path(args.bootloader) if args.bootloader else None
    flashcode_path = Path(args.flashcode) if args.flashcode else None
    keyfile_path = Path(args.keyfile) if args.keyfile else None

    if not any((firmware_path, bootloader_path, flashcode_path, keyfile_path)):
        print(
            "Error: specify at least one of --firmware, --flashcode, --bootloader, or --keyfile",
            file=sys.stderr,
        )
        return 1

    # Validate files exist
    if firmware_path and not firmware_path.exists():
        print(f"Error: firmware file not found: {firmware_path}", file=sys.stderr)
        return 1

    if bootloader_path and not bootloader_path.exists():
        print(
            f"Error: bootloader file not found: {bootloader_path}",
            file=sys.stderr,
        )
        return 1

    if flashcode_path and not flashcode_path.exists():
        print(
            f"Error: flashcode file not found: {flashcode_path}",
            file=sys.stderr,
        )
        return 1

    if keyfile_path and not keyfile_path.exists():
        print(
            f"Error: keyfile not found: {keyfile_path}",
            file=sys.stderr,
        )
        return 1

    # Determine port
    port = args.port
    if args.auto_detect:
        port = None  # Let SerialManager auto-detect

    # Determine baud rate
    baud = args.baud
    if baud not in (115200, 1000000, 1500000):
        print(
            f"Error: unsupported baud rate {baud}. Use 115200, 1000000, or 1500000",
            file=sys.stderr,
        )
        return 1

    # Build firmware spec
    spec = FirmwareSpec(
        bootloader=str(bootloader_path) if bootloader_path else None,
        code1=str(firmware_path) if firmware_path else None,
        code2=str(flashcode_path) if flashcode_path else None,
        keyfile=str(keyfile_path) if keyfile_path else None,
        mac=args.mac,
        force=args.force,
    )

    # Open serial and run burn
    sm = SerialManager(port=port, baudrate=baud, timeout=5.0)
    bp = BootloaderProtocol(
        serial=sm,
        chunk_size=1024,
        send_timeout=30.0,
        boot_timeout=args.boot_timeout,
        serial_monitor=args.serial_monitor,
    )

    # Progress bar
    total_size = 0
    if bootloader_path:
        total_size += bootloader_path.stat().st_size
    if firmware_path:
        total_size += firmware_path.stat().st_size
    if flashcode_path:
        total_size += flashcode_path.stat().st_size

    progress_bar = None

    def _progress(sent: int, total: int) -> None:
        nonlocal progress_bar
        if args.json:
            return
        if progress_bar is None or progress_bar.total != total or sent < progress_bar.n:
            if progress_bar is not None:
                progress_bar.close()
            progress_bar = tqdm(
                total=total,
                desc="Firmware download",
                unit="B",
                unit_scale=True,
                bar_format="{l_bar}{bar:30}{r_bar}",
            )
        progress_bar.update(sent - progress_bar.n)

    bp.progress_callback = _progress

    try:
        print(f"Opening serial port at {baud} baud...")
        sm.open()
        print("Serial port opened successfully")

        if args.manual_mode:
            print("Manual mode: assuming the device is already at the bootloader prompt.")
            enter_resp = BootloaderResponse(
                raw=b"",
                is_ok=True,
                is_bootloader_mode=True,
                text="manual mode",
            )
        else:
            print("Entering bootloader mode...")
            enter_resp = bp.enter_bootloader()
            print(
                f"  Mode: {'bootloader' if enter_resp.is_bootloader_mode else 'rom code'}"
            )

        print("Burning firmware...")
        result = bp.burn_firmware(spec, reboot=not args.no_reboot)

        if args.json:
            output = {
                "bootloader": enter_resp.raw.decode("utf-8", errors="replace"),
                "result": result.raw.decode("utf-8", errors="replace"),
                "is_download_success": result.is_download_success,
                "is_bootloader_mode": enter_resp.is_bootloader_mode,
            }
            print(json.dumps(output, indent=2))

        if result.is_download_success or result.is_ok:
            print(">>> Firmware burn SUCCESS <<<")
            return 0
        else:
            print(f">>> Firmware burn FAILED: {result.text} <<<")
            return 1

    except FileNotFoundError as e:
        print(f"Error: file not found: {e}", file=sys.stderr)
        return 1
    except TimeoutError as e:
        print(f"Error: timeout: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        if progress_bar is not None:
            progress_bar.close()
        bp.close()
