"""verify command — Read back and checksum-compare burned firmware."""

from __future__ import annotations

import argparse


def verify_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the verify subcommand parser."""
    p = subparsers.add_parser("verify", help="Verify burned firmware by reading back and comparing checksums")
    p.add_argument("--port", "-p", default=None, help="Serial port (e.g. /dev/ttyUSB0)")
    p.add_argument("--auto-detect", action="store_true", help="Auto-detect FT232 serial port")
    p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate (default: 1000000)")
    p.add_argument("--boot-timeout", default=5, type=int, help="Seconds to wait for bootloader prompt")
    p.add_argument("--firmware", "-f", required=True, type=str, help="Path to original firmware image for comparison")
    p.add_argument("--addr", default=None, type=str, help="Flash address to verify from")
    p.add_argument("--len", dest="length", default=None, type=str, help="Length to verify")
    p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    p.add_argument("--json", action="store_true", help="JSON output mode")


def verify_handler(args: argparse.Namespace) -> int:
    """Handle the verify command."""
    print("verify command — stub (F1)")
    print(f"  firmware: {args.firmware}")
    print(f"  port:     {args.port or 'default'}")
    print(f"  baud:     {args.baud}")
    return 0
