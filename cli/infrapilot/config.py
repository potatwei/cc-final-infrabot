"""User config persistence: ~/.infrapilot/config.yaml.

Recognized keys (all optional):
  api_url          : backend base URL (e.g. https://...amazonaws.com)
  api_key          : header sent as X-API-Key
  aws_region       : pinned to AWS_REGION/AWS_DEFAULT_REGION when running terraform
  expected_account : 12-digit AWS account id; deployment aborts if STS reports a different one
"""

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
