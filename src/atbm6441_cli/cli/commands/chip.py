"""chip command group — chipid, info, MAC, efuse, flash-id operations."""

from __future__ import annotations

import argparse
import json
import sys

from atbm6441_cli.protocol.flash_id import FlashIdReader


def chip_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the chip subcommand with sub-subcommands."""
    p = subparsers.add_parser("chip", help="Query chip information and manage MAC/efuse")

    sub = p.add_subparsers(dest="subcommand", help="Chip subcommands")
    sub.required = True

    # chipid
    chipid_p = sub.add_parser("chipid", help="Read chip ID / version register")
    chipid_p.add_argument("--port", "-p", default=None, help="Serial port")
    chipid_p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate")
    chipid_p.add_argument("--at-baud", default=115200, type=int, help="AT command baud rate")
    chipid_p.add_argument("--boot-timeout", default=5, type=int, help="Bootloader timeout")
    chipid_p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    chipid_p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    chipid_p.add_argument("--json", action="store_true", help="JSON output mode")

    # info
    info_p = sub.add_parser("info", help="Query firmware version via AT command")
    info_p.add_argument("--port", "-p", default=None, help="Serial port")
    info_p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate")
    info_p.add_argument("--at-baud", default=115200, type=int, help="AT command baud rate")
    info_p.add_argument("--boot-timeout", default=5, type=int, help="Bootloader timeout")
    info_p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    info_p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    info_p.add_argument("--json", action="store_true", help="JSON output mode")

    # read-mac
    read_mac_p = sub.add_parser("read-mac", help="Display the current MAC address")
    read_mac_p.add_argument("--port", "-p", default=None, help="Serial port")
    read_mac_p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate")
    read_mac_p.add_argument("--at-baud", default=115200, type=int, help="AT command baud rate")
    read_mac_p.add_argument("--boot-timeout", default=5, type=int, help="Bootloader timeout")
    read_mac_p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    read_mac_p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    read_mac_p.add_argument("--json", action="store_true", help="JSON output mode")

    # burn-mac
    burn_mac_p = sub.add_parser("burn-mac", help="Burn a MAC address to the chip")
    burn_mac_p.add_argument("--port", "-p", default=None, help="Serial port")
    burn_mac_p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate")
    burn_mac_p.add_argument("--at-baud", default=115200, type=int, help="AT command baud rate")
    burn_mac_p.add_argument("--boot-timeout", default=5, type=int, help="Bootloader timeout")
    burn_mac_p.add_argument("--mac", required=True, type=str, help="MAC address to burn (aa:bb:cc:dd:ee:ff)")
    burn_mac_p.add_argument("--force", action="store_true", help="Force MAC burn")
    burn_mac_p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    burn_mac_p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    burn_mac_p.add_argument("--json", action="store_true", help="JSON output mode")

    # flash-id
    flash_id_p = sub.add_parser("flash-id", help="Read flash JEDEC ID and determine size")
    flash_id_p.add_argument("--port", "-p", default=None, help="Serial port")
    flash_id_p.add_argument("--baud", "-b", default=1000000, type=int, help="Burn baud rate")
    flash_id_p.add_argument("--manual-mode", action="store_true", help="Skip auto GPIO control")
    flash_id_p.add_argument("--log-level", "-l", default="info", choices=["debug", "info", "warn", "error"], help="Log level")
    flash_id_p.add_argument("--json", action="store_true", help="JSON output mode")


def chip_handler(args: argparse.Namespace, subcommand: str) -> int:
    """Handle chip subcommands."""
    if subcommand == "flash-id":
        return _handle_flash_id(args)

    print(f"chip {subcommand} command — stub (F1)")
    return 0


def _handle_flash_id(args: argparse.Namespace) -> int:
    """Handle the chip flash-id subcommand."""
    from atbm6441_cli.protocol.uart import SerialManager

    serial = SerialManager(baudrate=args.baud)
    try:
        serial.open(args.port)
        reader = FlashIdReader(serial)
        info = reader.read_id()

        if args.json:
            output = {
                "manufacturer_id": f"0x{info.manufacturer_id:02X}",
                "manufacturer": info.manufacturer_name,
                "device_id": f"0x{info.device_id:04X}",
                "capacity_id": f"0x{info.capacity_id:02X}",
                "size_bytes": info.size_bytes,
                "size_human": info.size_human,
            }
            json.dump(output, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"Flash JEDEC ID:")
            print(f"  Manufacturer: 0x{info.manufacturer_id:02X} ({info.manufacturer_name})")
            print(f"  Device:       0x{info.device_id:04X}")
            print(f"  Capacity:     0x{info.capacity_id:02X}")
            print(f"  Size:         {info.size_human} ({info.size_bytes} bytes)")

        return 0
    except (TimeoutError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        serial.close()
