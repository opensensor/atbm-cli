"""mem command — Read/write memory via AT commands.

Commands:
    - AT+wmem <addr> <value>  Write 32-bit value to memory
    - AT+WIFI_ETF_RMEM <addr> <len>  Read bytes from memory
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ...protocol.bootloader import BootloaderProtocol
from ...protocol.uart import SerialManager

logger = logging.getLogger(__name__)


def mem_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the mem subcommand parser."""
    p = subparsers.add_parser(
        "mem",
        help="Read/write memory via AT commands",
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
        help="Baud rate (default: 1000000)",
    )
    sub = p.add_subparsers(dest="mem_action", help="Memory operation")

    # Write subcommand (use 'w' to avoid conflict with top-level 'write')
    w = sub.add_parser("w", help="Write 32-bit value to memory")
    w.add_argument("address", type=int, help="Memory address (hex)")
    w.add_argument("value", type=int, help="32-bit value to write (hex)")
    w.add_argument(
        "--json", action="store_true", help="JSON output"
    )

    # Read subcommand
    r = sub.add_parser("r", help="Read bytes from memory")
    r.add_argument("address", type=int, help="Memory address (hex)")
    r.add_argument(
        "--length",
        "-l",
        type=int,
        default=4,
        help="Number of bytes to read (default: 4)",
    )
    r.add_argument(
        "--json", action="store_true", help="JSON output"
    )

    p.add_argument(
        "--log-level",
        "-l",
        default="info",
        choices=["debug", "info", "warn", "error"],
        help="Log level",
    )


def mem_handler(args: argparse.Namespace) -> int:
    """Handle the mem command."""
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = args.port if not args.auto_detect else None
    if args.baud not in (115200, 1000000, 1500000):
        print(
            f"Error: unsupported baud rate {args.baud}",
            file=sys.stderr,
        )
        return 1

    sm = SerialManager(port=port, baudrate=args.baud, timeout=5.0)
    bp = BootloaderProtocol(serial=sm, chunk_size=1024, boot_timeout=5.0)

    try:
        print(f"Opening serial port at {args.baud} baud...")
        sm.open()

        if args.mem_action == "w":
            if not (0 <= args.value <= 0xFFFFFFFF):
                print(
                    f"Error: value 0x{args.value:X} is not a 32-bit integer",
                    file=sys.stderr,
                )
                return 1

            print(f"Writing 0x{args.value:08X} to addr 0x{args.address:08X}...")
            resp = bp.write_memory(args.address, args.value)
            print(f"  Response: {resp.text}")

            if args.json:
                output = {
                    "address": f"0x{args.address:08X}",
                    "value": f"0x{args.value:08X}",
                    "response": resp.text,
                    "is_error": resp.is_error,
                }
                print(json.dumps(output, indent=2))

            return 0 if not resp.is_error else 1

        elif args.mem_action == "r":
            print(f"Reading {args.length} bytes from addr 0x{args.address:08X}...")
            resp = bp.read_memory(args.address, args.length)
            print(f"  Response: {resp.text}")

            if args.json:
                output = {
                    "address": f"0x{args.address:08X}",
                    "length": args.length,
                    "response": resp.text,
                }
                print(json.dumps(output, indent=2))

            return 0

        else:
            print(
                "Error: specify 'w' or 'r' subcommand",
                file=sys.stderr,
            )
            return 1

    except (TimeoutError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        bp.close()
