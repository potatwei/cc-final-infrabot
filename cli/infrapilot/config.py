"""User config persistence: ~/.infrapilot/config.yaml (api_url, api_key)."""

from pathlib import Path

import yaml

USER_CONFIG_DIR = Path.home() / ".infrapilot"
USER_CONFIG = USER_CONFIG_DIR / "config.yaml"


def load_user_config() -> dict:
    if not USER_CONFIG.exists():
        return {}
    return yaml.safe_load(USER_CONFIG.read_text()) or {}


def save_user_config(cfg: dict) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False))
