"""
Config loader and validator for the Music Culture Observation Engine.
Reads and validates an instance YAML config file.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REQUIRED_TOP_LEVEL_KEYS = ["instance", "sources", "output"]
REQUIRED_INSTANCE_KEYS = ["name", "purpose_context"]
REQUIRED_OUTPUT_KEYS = ["vault_path", "inbox_folder"]
REQUIRED_SOURCE_KEYS = {
    "rss": ["feeds"],
    "reddit": ["subreddits"],
    "beatport": ["charts"],
}


def load(config_path: str) -> dict:
    """
    Load and validate an instance config YAML file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Validated config dict.

    Raises:
        FileNotFoundError: If config_path does not exist.
        ValueError: If required keys are missing or config is malformed.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"Config YAML parse error: {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping at the top level.")

    _check_required_keys(config, REQUIRED_TOP_LEVEL_KEYS, "top level")
    _check_required_keys(config["instance"], REQUIRED_INSTANCE_KEYS, "instance")
    _check_required_keys(config["output"], REQUIRED_OUTPUT_KEYS, "output")

    # Validate each enabled source's required keys
    sources = config.get("sources", {})
    for source_name, required_keys in REQUIRED_SOURCE_KEYS.items():
        source_config = sources.get(source_name, {})
        if source_config.get("enabled", False):
            _check_required_keys(
                source_config, required_keys, f"sources.{source_name}"
            )

    # Resolve vault_path to absolute
    vault_path = config["output"]["vault_path"]
    config["output"]["vault_path"] = str(Path(vault_path).expanduser().resolve())

    logger.info(
        "Config loaded: instance='%s', vault='%s'",
        config["instance"]["name"],
        config["output"]["vault_path"],
    )
    return config


def _check_required_keys(mapping: dict, keys: list[str], context: str) -> None:
    """Raise ValueError if any required key is missing from mapping."""
    if not isinstance(mapping, dict):
        raise ValueError(
            f"Config section '{context}' must be a mapping, got {type(mapping).__name__}."
        )
    missing = [k for k in keys if k not in mapping]
    if missing:
        raise ValueError(
            f"Config missing required key(s) in {context}: {', '.join(missing)}"
        )
