"""Configuration management for The Reserve Automation."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, field_validator

from .exceptions import ConfigurationError


class Config(BaseModel):
    """
    Application configuration.

    Loads from multiple YAML files with precedence:
      1. user.yaml (highest priority, gitignored)
      2. Environment variables
      3. default.yaml
    """

    # Project
    project: dict = {}

    # Paths
    paths: dict = {}

    # LLM configuration
    llm: dict = {}

    # Parser settings
    parsers: dict = {}

    # Extraction settings
    extraction: dict = {}

    # Git settings
    git: dict = {}

    # Logging settings
    logging: dict = {}

    @property
    def vault_path(self) -> Optional[Path]:
        """Get vault path from config."""
        vault_str = self.paths.get("vault")
        return Path(vault_str) if vault_str else None

    @property
    def config_dir(self) -> Path:
        """Get config directory path."""
        return Path(self.paths.get("config_dir", "config"))

    @property
    def templates_dir(self) -> Path:
        """Get templates directory path."""
        return Path(self.paths.get("templates_dir", "templates"))

    @property
    def cache_dir(self) -> Path:
        """Get cache directory path."""
        return Path(self.paths.get("cache_dir", ".cache"))

    @property
    def logs_dir(self) -> Path:
        """Get logs directory path."""
        return Path(self.paths.get("logs_dir", "logs"))

    @field_validator("paths")
    @classmethod
    def validate_vault_path(cls, v: dict) -> dict:
        """Validate vault path if provided."""
        if vault := v.get("vault"):
            vault_path = Path(vault)
            if not vault_path.exists():
                raise ConfigurationError(f"Vault path does not exist: {vault_path}")
        return v

    @classmethod
    def load(cls, config_file: Optional[Path] = None) -> "Config":
        """
        Load configuration from files.

        Args:
            config_file: Optional user config file (overrides default)

        Returns:
            Merged configuration

        Raises:
            ConfigurationError: If configuration is invalid
        """
        try:
            # 1. Load default config
            default_path = Path("config/default.yaml")
            if not default_path.exists():
                raise ConfigurationError(f"Default config not found: {default_path}")

            with open(default_path) as f:
                config = yaml.safe_load(f) or {}

            # 2. Load LLM config
            llm_path = Path(config.get("llm", {}).get("config_file", "config/llm.yaml"))
            if llm_path.exists():
                with open(llm_path) as f:
                    config["llm"] = yaml.safe_load(f) or {}
            else:
                raise ConfigurationError(f"LLM config not found: {llm_path}")

            # 3. Load user config if exists
            user_path = config_file or Path("config/user.yaml")
            if user_path.exists():
                with open(user_path) as f:
                    user_config = yaml.safe_load(f) or {}
                    config = cls._deep_merge(config, user_config)

            # 4. Override with environment variables
            config = cls._apply_env_overrides(config)

            return cls(**config)

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}")

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = Config._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _apply_env_overrides(config: dict) -> dict:
        """Apply environment variable overrides."""
        # Example: RESERVE_VAULT_PATH overrides paths.vault
        if vault_env := os.getenv("RESERVE_VAULT_PATH"):
            config.setdefault("paths", {})
            config["paths"]["vault"] = vault_env

        # RESERVE_LM_STUDIO_URL overrides LM Studio base URLs
        if lm_studio_url := os.getenv("RESERVE_LM_STUDIO_URL"):
            if "llm" in config and "providers" in config["llm"]:
                for provider_name, provider_config in config["llm"]["providers"].items():
                    if provider_config.get("provider") == "lm_studio":
                        provider_config["base_url"] = lm_studio_url

        return config

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by key (dot notation supported)."""
        keys = key.split(".")
        value = self.model_dump()

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value if value is not None else default
