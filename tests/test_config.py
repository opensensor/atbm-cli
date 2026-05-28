"""Tests for config file support (F3)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from atbm6441_cli.config import Config, get_config, merge_config_with_args


class TestConfig:
    """Tests for Config class."""

    def test_defaults(self):
        """Test default values."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()

            assert config.get("port") is None
            assert config.get("baud") == "1000000"
            assert config.get("at_baud") == "115200"
            assert config.get("boot_timeout") == "5"
        finally:
            os.unlink(config_path)

    def test_set_and_get(self):
        """Test setting and getting config values."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            config.set("port", "/dev/ttyUSB1")
            assert config.get("port") == "/dev/ttyUSB1"
        finally:
            os.unlink(config_path)

    def test_save_and_load(self):
        """Test saving and loading config."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            config.set("port", "/dev/ttyUSB2")
            config.set("baud", "1500000")
            config.save()

            # Reload from saved file
            config2 = Config(config_path)
            config2.load()
            assert config2.get("port") == "/dev/ttyUSB2"
            assert config2.get("baud") == "1500000"
        finally:
            os.unlink(config_path)

    def test_get_int(self):
        """Test getting integer config values."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            config.set("baud", "1000000")
            assert config.get_int("baud") == 1000000
        finally:
            os.unlink(config_path)

    def test_get_int_invalid(self):
        """Test getting invalid integer config values (falls back to default)."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            config.set("baud", "not_a_number")
            assert config.get_int("baud", default=9600) == 9600
        finally:
            os.unlink(config_path)

    def test_get_int_missing_key(self):
        """Test getting missing integer config values (falls back to default)."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            assert config.get_int("nonexistent", default=42) == 42
        finally:
            os.unlink(config_path)

    def test_to_dict(self):
        """Test converting config to dictionary."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            config.set("port", "/dev/ttyUSB0")
            d = config.to_dict()
            assert d["port"] == "/dev/ttyUSB0"
            assert d["baud"] == "1000000"
        finally:
            os.unlink(config_path)

    def test_repr(self):
        """Test Config __repr__."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            config.load()
            assert "Config" in repr(config)
            assert config_path in repr(config)
        finally:
            os.unlink(config_path)

    def test_config_path_property(self):
        """Test config_path property."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = Config(config_path)
            assert config.config_path == Path(config_path)
        finally:
            os.unlink(config_path)


class TestGetConfig:
    """Tests for get_config function."""

    def test_get_config_loads(self):
        """Test get_config loads config."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = get_config(config_path)
            assert config.get("baud") == "1000000"
        finally:
            os.unlink(config_path)


class TestMergeConfigWithArgs:
    """Tests for merge_config_with_args function."""

    def test_args_override_config(self):
        """Test CLI args override config values."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = get_config(config_path)
            config.set("port", "/dev/ttyUSB0")
            config.set("baud", "115200")

            merged = merge_config_with_args(config, {"port": "/dev/ttyUSB1", "baud": 1000000})
            assert merged["port"] == "/dev/ttyUSB1"
            assert merged["baud"] == "1000000"
        finally:
            os.unlink(config_path)

    def test_none_args_preserve_config(self):
        """Test None CLI args preserve config values."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = get_config(config_path)
            config.set("port", "/dev/ttyUSB0")

            merged = merge_config_with_args(config, {"port": None})
            assert merged["port"] == "/dev/ttyUSB0"
        finally:
            os.unlink(config_path)

    def test_new_args_added(self):
        """Test new CLI args are added to merged dict."""
        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as f:
            config_path = f.name

        try:
            config = get_config(config_path)
            config.load()

            merged = merge_config_with_args(config, {"at_baud": 9600})
            assert merged["at_baud"] == "9600"
        finally:
            os.unlink(config_path)
