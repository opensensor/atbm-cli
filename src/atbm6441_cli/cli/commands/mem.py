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


def _parse_hex_int(value: str) -> int:
    """Parse a hex integer, accepting both 0x-prefixed and bare SDK-style hex."""
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return int(text, 16)


def _parse_length(value: str) -> int:
    """Parse a byte length as decimal by default, with optional 0x hex."""
    text = value.strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    return int(text, 10)


def _add_common_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    """Add mem-level options to either the main parser or a subcommand parser."""
    default = argparse.SUPPRESS if suppress_defaults else None
    baud_default = argparse.SUPPRESS if suppress_defaults else 1000000
    log_default = argparse.SUPPRESS if suppress_defaults else "info"

    parser.add_argument(
        "--port", "-p", default=default, help="Serial port"
    )
    parser.add_argument(
        "--auto-detect",
        action="store_true",
        default=argparse.SUPPRESS if suppress_defaults else False,
        help="Auto-detect FT232 serial port",
    )
    parser.add_argument(
        "--baud",
        "-b",
        default=baud_default,
        type=int,
        help="Baud rate (default: 1000000)",
    )
    parser.add_argument(
        "--device",
        choices=["6441", "6446", "6447"],
        default=default,
        help="Chip model (accepted for compatibility; not required for memory access)",
    )
    parser.add_argument(
        "--log-level",
        default=log_default,
        choices=["debug", "info", "warn", "error"],
        help="Log level",
    )


def mem_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the mem subcommand parser."""
    p = subparsers.add_parser(
        "mem",
        help="Read/write memory via AT commands",
    )
    _add_common_options(p)
    sub = p.add_subparsers(dest="mem_action", help="Memory operation")

    # Write subcommand (use 'w' to avoid conflict with top-level 'write')
    w = sub.add_parser("w", aliases=["write"], help="Write 32-bit value to memory")
    _add_common_options(w, suppress_defaults=True)
    w.add_argument("address", type=_parse_hex_int, help="Memory address (hex)")
    w.add_argument("value", type=_parse_hex_int, help="32-bit value to write (hex)")
    w.add_argument(
        "--json", action="store_true", help="JSON output"
    )

    # Read subcommand
    r = sub.add_parser("r", aliases=["read"], help="Read bytes from memory")
    _add_common_options(r, suppress_defaults=True)
    r.add_argument("address", type=_parse_hex_int, help="Memory address (hex)")
    r.add_argument(
        "length_pos",
        nargs="?",
        type=_parse_length,
        help="Number of bytes to read (default: 4)",
    )
    r.add_argument(
        "--length",
        "-l",
        type=_parse_length,
        default=4,
        help="Number of bytes to read (default: 4)",
    )
    r.add_argument(
        "--json", action="store_true", help="JSON output"
    )

    p.set_defaults(handler=mem_handler)


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

        if args.mem_action in ("w", "write"):
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

        elif args.mem_action in ("r", "read"):
            length = args.length_pos if args.length_pos is not None else args.length
            print(f"Reading {length} bytes from addr 0x{args.address:08X}...")
            resp = bp.read_memory(args.address, length)
            print(f"  Response: {resp.text}")

            if args.json:
                output = {
                    "address": f"0x{args.address:08X}",
                    "length": length,
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
