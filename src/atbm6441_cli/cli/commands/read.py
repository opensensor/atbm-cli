"""read command — Read flash content to a file."""

from __future__ import annotations

import argparse
import json
import logging
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
    p.add_argument("--device", choices=["6441", "6446", "6447"], help="Chip model (skip JEDEC for 6446/6447)")
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

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

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

    serial = SerialManager(port=args.port if not args.auto_detect else None, baudrate=args.baud)
    try:
        serial.open()

        # Enter bootloader mode and create protocol instance
        bootloader = BootloaderProtocol(serial, boot_timeout=args.boot_timeout)
        try:
            bootloader.enter_bootloader()
        except TimeoutError:
            print("Warning: timeout entering bootloader mode, continuing anyway", file=sys.stderr)

        flash_size = int(args.flash_size, 16) if args.flash_size else None
        if flash_size is None and args.read_all:
            # Skip JEDEC ID for 6446/6447 (they don't support it)
            if args.device in ("6446", "6447"):
                flash_size = 0x400000  # Default 4MB
                print(f"Using default 4MB flash size (JEDEC not supported on {args.device})", file=sys.stderr)
            else:
                # Try to discover flash size via JEDEC ID, fall back to 4MB
                try:
                    from atbm6441_cli.protocol.flash_id import FlashIdReader
                    id_reader = FlashIdReader(serial)
                    info = id_reader.read_id()
                    flash_size = info.size_bytes
                    print(f"Discovered flash size: {info.size_human}", file=sys.stderr)
                except (TimeoutError, ValueError) as e:
                    flash_size = 0x400000  # Default 4MB
                    print(f"Warning: JEDEC ID failed ({e}), using default 4MB", file=sys.stderr)

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
