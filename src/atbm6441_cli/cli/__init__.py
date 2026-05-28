"""ATBM6441 CLI — Main entry point with argparse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on the path so we can import submodules
_src = Path(__file__).resolve().parent.parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from atbm6441_cli import __version__
from atbm6441_cli.cli.commands.burn import burn_parser, burn_handler
from atbm6441_cli.cli.commands.verify import verify_parser, verify_handler
from atbm6441_cli.cli.commands.read import read_parser, read_handler
from atbm6441_cli.cli.commands.write import write_parser, write_handler
from atbm6441_cli.cli.commands.chip import chip_parser, chip_handler
from atbm6441_cli.cli.commands.key import key_parser, key_handler
from atbm6441_cli.cli.commands.info import info_parser, info_handler
from atbm6441_cli.cli.commands.mem import mem_parser, mem_handler


def create_parser() -> argparse.ArgumentParser:
    """Create the root argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="atbm6441-cli",
        description="ATBM6441 CLI — Flash firmware to AltoBeam ATBM6441 WiFi IoT chips via UART.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.required = True

    # burn
    burn_parser(subparsers)

    # verify
    verify_parser(subparsers)

    # read
    read_parser(subparsers)

    # write
    write_parser(subparsers)

    # chip (with sub-subcommands)
    chip_parser(subparsers)

    # key (burn key data)
    key_parser(subparsers)

    # info (query chip info)
    info_parser(subparsers)

    # mem (read/write memory)
    mem_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    # Dispatch to the appropriate handler
    handler = getattr(args, "handler", None)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
