"""read command — Read flash content to a file."""

from __future__ import annotations

import argparse
import json
import os
import sys


def read_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the read subcommand parser."""
    p = subparsers.add_parser("read", help="Read flash content from the chip and save to a file")
    p.add_argument("--port", "-p", default=None, help="Serial port (e.g. /dev/ttyUSB0)")
    p.add_argument("--auto-detect", action="store_true", help="Auto-detect FT232 serial port")
    p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate (default: 1000000)")
    p.add_argument("--boot-timeout", default=5, type=int, help="Seconds to wait for bootloader prompt")
    p.add_argument("--addr", type=str, help="Flash address to read from (hex, e.g. 0x000000)")
    p.add_argument("--len", dest="length", type=str, help="Number of bytes to read (hex, e.g. 0x100000)")
    p.add_argument("--read-all", action="store_true", help="Read entire flash (auto-discover size)")
    p.add_argument("--output", "-o", required=True, type=str, help="Output file path")
    p.add_argument("--flash-size", type=str, help="Override flash size (hex, e.g. 0x400000 for 4MB)")
    p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    p.add_argument("--json", action="store_true", help="JSON output mode")
    p.set_defaults(handler=read_handler)


def read_handler(args: argparse.Namespace) -> int:
    """Handle the read command."""
    from atbm6441_cli.protocol.bootloader import BootloaderProtocol
    from atbm6441_cli.protocol.flash_reader import FlashReader
    from atbm6441_cli.protocol.uart import SerialManager

    # Validate: need --read-all OR (--addr + --len)
    if args.read_all:
        if args.addr or args.length:
            print("Error: --read-all cannot be used with --addr/--len", file=sys.stderr)
            return 1
    elif args.addr and args.length:
        pass  # OK: explicit range
    else:
        print("Error: specify --read-all or both --addr and --len", file=sys.stderr)
        return 1

    # Parse hex values
    addr = int(args.addr, 16) if args.addr else 0
    length = int(args.length, 16) if args.length else 0

    serial = SerialManager(baudrate=args.baud)
    try:
        serial.open(args.port or (None if args.auto_detect else None))
        if args.auto_detect:
            serial.open()  # triggers auto-detect

        # Enter bootloader mode and create protocol instance
        bootloader = BootloaderProtocol(serial)
        bootloader.enter_bootloader(timeout=args.boot_timeout)

        flash_size = int(args.flash_size, 16) if args.flash_size else None
        reader = FlashReader(serial, flash_size=flash_size, bootloader=bootloader)

        def progress_callback(bytes_read: int, total: int) -> None:
            pct = (bytes_read / total * 100) if total else 0
            sys.stderr.write(f"\rProgress: {pct:5.1f}% ({bytes_read}/{total} bytes)  ")
            sys.stderr.flush()

        if args.read_all:
            data = reader.read_all(progress_callback=progress_callback)
            sys.stderr.write("\n")
            sys.stderr.flush()
            print(f"Read {len(data)} bytes from flash (auto-discovered size)")
        else:
            data = reader.read_range(addr, length, progress_callback=progress_callback)
            sys.stderr.write("\n")
            sys.stderr.flush()
            print(f"Read {len(data)} bytes from 0x{addr:08X}")

        # Write to output file
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(args.output, "wb") as f:
            f.write(data)

        print(f"Wrote {len(data)} bytes to {args.output}")

        if args.json:
            output = {
                "address": f"0x{addr:08X}",
                "length": len(data),
                "output": args.output,
            }
            json.dump(output, sys.stdout, indent=2)
            sys.stdout.write("\n")

        return 0
    except (TimeoutError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        serial.close()
