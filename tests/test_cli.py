"""Tests for CLI skeleton (F1)."""

from __future__ import annotations

import subprocess

from atbm6441_cli.cli import create_parser


def test_cli_help():
    """Verify CLI help output lists all subcommands."""
    result = subprocess.run(["atbm6441-cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "burn" in result.stdout
    assert "verify" in result.stdout
    assert "read" in result.stdout
    assert "write" in result.stdout
    assert "chip" in result.stdout


def test_cli_version():
    """Verify --version flag works."""
    result = subprocess.run(["atbm6441-cli", "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_burn_help():
    """Verify burn subcommand help."""
    result = subprocess.run(["atbm6441-cli", "burn", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--firmware" in result.stdout
    assert "--port" in result.stdout
    assert "--baud" in result.stdout


def test_burn_underscore_aliases_parse():
    """Verify copied underscore burn flags map to canonical argparse dests."""
    parser = create_parser()
    args = parser.parse_args(
        [
            "burn",
            "--manual_mode",
            "--no_reboot",
            "--serial_monitor",
            "--tx_delay_ms",
            "2",
            "--firmware",
            "code1_original.bin",
            "--flashcode",
            "code2_no_reboot.bin",
        ]
    )

    assert args.manual_mode is True
    assert args.no_reboot is True
    assert args.serial_monitor is True
    assert args.tx_delay_ms == 2


def test_chip_subcommands():
    """Verify chip subcommands exist."""
    result = subprocess.run(["atbm6441-cli", "chip", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "chipid" in result.stdout
    assert "info" in result.stdout
    assert "read-mac" in result.stdout
    assert "burn-mac" in result.stdout
