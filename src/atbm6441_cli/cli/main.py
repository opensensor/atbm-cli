"""ATBM6441 CLI — Main entry point with click framework."""

from __future__ import annotations

import sys
from pathlib import Path

import click

# Ensure src/ is on the path so we can import submodules
_src = Path(__file__).resolve().parent.parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from atbm6441_cli import __version__
from atbm6441_cli.cli.commands.burn import burn
from atbm6441_cli.cli.commands.chip import chip
from atbm6441_cli.cli.commands.read import read_cmd
from atbm6441_cli.cli.commands.verify import verify
from atbm6441_cli.cli.commands.write import write_cmd


@click.group()
@click.version_option(version=__version__, prog_name="atbm6441-cli")
@click.help_option("-h", "--help")
def cli() -> None:
    """ATBM6441 CLI — Flash firmware to AltoBeam ATBM6441 WiFi IoT chips via UART."""
    pass


# Register subcommands
cli.add_command(burn)
cli.add_command(verify)
cli.add_command(read_cmd)
cli.add_command(write_cmd)
cli.add_command(chip)


if __name__ == "__main__":
    cli()
