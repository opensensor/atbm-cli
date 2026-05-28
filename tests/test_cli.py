"""Tests for CLI skeleton (F1)."""

from __future__ import annotations

import subprocess


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


def test_chip_subcommands():
    """Verify chip subcommands exist."""
    result = subprocess.run(["atbm6441-cli", "chip", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "chipid" in result.stdout
    assert "info" in result.stdout
    assert "read-mac" in result.stdout
    assert "burn-mac" in result.stdout
