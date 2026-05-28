"""write command — Write a binary to a specific flash address."""

from __future__ import annotations

import argparse


def write_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the write subcommand parser."""
    p = subparsers.add_parser("write", help="Write a binary file to a specific flash address on the chip")
    p.add_argument("--port", "-p", default=None, help="Serial port (e.g. /dev/ttyUSB0)")
    p.add_argument("--auto-detect", action="store_true", help="Auto-detect FT232 serial port")
    p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate (default: 1000000)")
    p.add_argument("--boot-timeout", default=5, type=int, help="Seconds to wait for bootloader prompt")
    p.add_argument("--addr", required=True, type=str, help="Flash address to write to (hex, e.g. 0x100000)")
    p.add_argument("--data", "-d", required=True, type=str, help="Binary data file to write")
    p.add_argument("--force", action="store_true", help="Force write (disable write protection)")
    p.add_argument("--no-flash-protect", action="store_true", help="Disable flash write protection before write")
    p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    p.add_argument("--json", action="store_true", help="JSON output mode")
    p.set_defaults(handler=write_handler)


def write_handler(args: argparse.Namespace) -> int:
    """Handle the write command."""
    print("write command — stub (F1)")
    print(f"  addr: {args.addr}")
    print(f"  data: {args.data}")
    return 0
