"""info command — Query chip info via AT commands.

Commands:
    - AT+GMR          Get modem info
    - AT+GET_SDK_VER  Get SDK version
    - AT+VENVER       Get hardware version
    - AT+WIFI_GET_FWINFO  Get firmware info
    - AT+WIFI_STATUS    Get WiFi status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ...protocol.bootloader import BootloaderProtocol
from ...protocol.uart import SerialManager

logger = logging.getLogger(__name__)


def info_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the info subcommand parser."""
    p = subparsers.add_parser(
        "info",
        help="Query chip info via AT commands",
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
        default=115200,
        type=int,
        help="AT command baud rate (default: 115200)",
    )
    p.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["gmr", "sdk", "venver", "fwinfo", "status", "all"],
        help="AT command to send (default: all)",
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


def info_handler(args: argparse.Namespace) -> int:
    """Handle the info command."""
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

    results: dict[str, str] = {}

    try:
        print(f"Opening serial port at {args.baud} baud...")
        sm.open()

        cmd_map = {
            "gmr": ("AT+GMR", bp.get_modem_info),
            "sdk": ("AT+GET_SDK_VER", bp.get_sdk_version),
            "venver": ("AT+VENVER", bp.get_hw_version),
            "fwinfo": ("AT+WIFI_GET_FWINFO", bp.get_modem_info),
            "status": ("AT+WIFI_STATUS", bp.get_modem_info),
        }

        if args.command == "all":
            for name, (_, func) in cmd_map.items():
                print(f"Sending {name}...")
                resp = func()
                results[name] = resp.raw.decode("utf-8", errors="replace").strip()
                print(f"  {resp.text}")
        else:
            name, (_, func) = cmd_map[args.command]
            print(f"Sending {name}...")
            resp = func()
            results[name] = resp.raw.decode("utf-8", errors="replace").strip()
            print(f"  {resp.text}")

        if args.json:
            output = {"baud": args.baud, "results": results}
            print(json.dumps(output, indent=2))

        return 0

    except (TimeoutError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        bp.close()
