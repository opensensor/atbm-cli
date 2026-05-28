"""Config file support — ~/.atbm6441-cli.ini."""

from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default configuration values
DEFAULTS = {
    "port": None,  # No default port — must be specified or auto-detected
    "baud": "1000000",
    "at_baud": "115200",
    "boot_timeout": "5",
}

CONFIG_FILENAME = ".atbm6441-cli.ini"


class Config:
    """Manages the ATBM6441 CLI configuration file."""

    def __init__(self, config_path: str | None = None) -> None:
        """Initialize config.

        Args:
            config_path: Optional path to config file. Defaults to ~/.atbm6441-cli.ini.
        """
        if config_path:
            self._config_path = Path(config_path)
        else:
            self._config_path = Path.home() / CONFIG_FILENAME

        self._parser = configparser.ConfigParser()
        self._loaded = False

    @property
    def config_path(self) -> Path:
        """Path to the config file."""
        return self._config_path

    def load(self) -> None:
        """Load configuration from file.

        If the file doesn't exist, initializes with defaults.
        """
        if self._config_path.exists():
            logger.info("Loading config from %s", self._config_path)
            self._parser.read(self._config_path)
            self._loaded = True
        else:
            logger.info("Config file not found at %s, using defaults", self._config_path)
            self._loaded = False

    def save(self) -> None:
        """Save configuration to file."""
        if not self._loaded:
            self.load()

        # Ensure the config file has the necessary sections
        if not self._parser.has_section("settings"):
            self._parser.add_section("settings")

        # Write any values that are in the parser (user-set or loaded)
        for key, value in self._parser.items("settings"):
            self._parser.set("settings", key, str(value))

        # Ensure directory exists
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._config_path, "w") as f:
            self._parser.write(f)

        logger.info("Config saved to %s", self._config_path)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get a config value.

        Args:
            key: Configuration key (e.g. 'port', 'baud').
            default: Default value if key not found.

        Returns:
            Config value as string, or default.
        """
        if not self._loaded:
            self.load()

        try:
            return self._parser.get("settings", key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default or DEFAULTS.get(key)

    def set(self, key: str, value: str) -> None:
        """Set a config value.

        Args:
            key: Configuration key.
            value: Value to set.
        """
        if not self._loaded:
            self.load()

        if not self._parser.has_section("settings"):
            self._parser.add_section("settings")

        self._parser.set("settings", key, value)
        logger.debug("Set config %s = %s", key, value)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer config value.

        Args:
            key: Configuration key.
            default: Default value if key not found or invalid.

        Returns:
            Config value as integer.
        """
        value = self.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning("Invalid integer value for %s: %s, using default %d", key, value, default)
            return default

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary.

        Returns:
            Dictionary of config values.
        """
        if not self._loaded:
            self.load()

        result = dict(DEFAULTS)
        if self._parser.has_section("settings"):
            result.update(dict(self._parser.items("settings")))
        return result

    def __repr__(self) -> str:
        return f"Config(path={self._config_path}, loaded={self._loaded})"


def get_config(config_path: str | None = None) -> Config:
    """Get a Config instance, loading it.

    Args:
        config_path: Optional path to config file.

    Returns:
        Config instance with values loaded.
    """
    config = Config(config_path)
    config.load()
    return config


def merge_config_with_args(config: Config, args: dict[str, Any]) -> dict[str, Any]:
    """Merge config values with CLI args (args override config).

    Args:
        config: Config instance.
        args: CLI argument dictionary (may contain None for unset values).

    Returns:
        Merged dictionary with args taking precedence.
    """
    result = dict(config.to_dict())

    # Override with CLI args where provided (non-None)
    for key, cli_value in args.items():
        # Map CLI arg names to config keys
        config_key = key.replace("-", "_")
        if cli_value is not None:
            result[config_key] = str(cli_value)

    return result
