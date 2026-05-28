"""key command — Burn KEY data to ATBM6441 flash via AT+wmem.

Protocol:
    1. Open UART at 1,000,000 baud
    2. Send AT+START → enter bootloader mode
    3. Parse KEY file (CSV or hex string)
    4. Send AT+wmem <addr> <value> for each 4-byte chunk
    5. Send AT+REBOOT → execute
"""

from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from pathlib import Path

from ...protocol.bootloader import (
    BootloaderProtocol,
    KEY1_ADDR,
    KEY2_ADDR,
)
from ...protocol.uart import SerialManager

logger = logging.getLogger(__name__)


def key_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the key subcommand parser."""
    p = subparsers.add_parser(
        "key",
        help="Burn KEY data to ATBM6441 flash via AT+wmem",
    )
    p.add_argument(
        "--port", "-p", default=None, help="Serial port"
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
        "--keyfile",
        required=True,
        type=str,
        help="Path to KEY file (CSV/TXT with hex key values)",
    )
    p.add_argument(
        "--key1-addr",
        type=int,
        default=KEY1_ADDR,
        help=f"KEY1 destination address (default: 0x{KEY1_ADDR:06X})",
    )
    p.add_argument(
        "--key2-addr",
        type=int,
        default=KEY2_ADDR,
        help=f"KEY2 destination address (default: 0x{KEY2_ADDR:06X})",
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


def key_handler(args: argparse.Namespace) -> int:
    """Handle the key command."""
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    keyfile_path = Path(args.keyfile)
    if not keyfile_path.exists():
        print(
            f"Error: keyfile not found: {keyfile_path}",
            file=sys.stderr,
        )
        return 1

    port = args.port if not args.auto_detect else None
    if args.baud not in (115200, 1000000, 1500000):
        print(
            f"Error: unsupported baud rate {args.baud}",
            file=sys.stderr,
        )
        return 1

    # Parse KEY file
    with open(keyfile_path, "r") as f:
        content = f.read().strip()

    # Extract hex keys
    keys: list[str] = []
    if "," in content:
        import csv

        reader = csv.reader(content.splitlines())
        for row in reader:
            for val in row:
                val = val.strip()
                if val and val.lower() != "key":
                    keys.append(val)
    else:
        keys = [content]

    if not keys:
        print("Error: no KEY data found in file", file=sys.stderr)
        return 1

    # Convert keys to 4-byte chunks
    chunks: list[tuple[int, int]] = []
    for key_str in keys:
        try:
            key_bytes = bytes.fromhex(key_str.replace(" ", ""))
        except ValueError:
            print(
                f"Warning: invalid key format: {key_str}, skipping",
                file=sys.stderr,
            )
            continue

        for i in range(0, len(key_bytes), 4):
            chunk = key_bytes[i : i + 4]
            if len(chunk) == 4:
                value = struct.unpack(">I", chunk)[0]
                addr = args.key1_addr + i
                chunks.append((addr, value))

    if not chunks:
        print("Error: no valid KEY chunks extracted", file=sys.stderr)
        return 1

    # Open serial and burn
    sm = SerialManager(port=port, baudrate=args.baud, timeout=5.0)
    bp = BootloaderProtocol(serial=sm, chunk_size=1024, boot_timeout=5.0)

    try:
        print(f"Opening serial port at {args.baud} baud...")
        sm.open()

        print("Entering bootloader mode...")
        enter_resp = bp.enter_bootloader()
        print(
            f"  Mode: {'bootloader' if enter_resp.is_bootloader_mode else 'rom code'}"
        )

        print(f"Burning {len(chunks)} KEY chunks...")
        results: list[str] = []
        for addr, value in chunks:
            resp = bp.write_memory(addr, value)
            results.append(
                f"  0x{addr:08X} = 0x{value:08X} → {resp.text}"
            )
            if resp.is_error:
                print(f"Error: KEY write failed at 0x{addr:08X}: {resp.text}")
                return 1

        if args.json:
            output = {
                "bootloader_mode": enter_resp.is_bootloader_mode,
                "chunks_written": len(chunks),
                "results": results,
            }
            print(json.dumps(output, indent=2))
        else:
            for line in results:
                print(line)

        print(">>> KEY burn SUCCESS <<<")
        return 0

    except (TimeoutError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        bp.close()
