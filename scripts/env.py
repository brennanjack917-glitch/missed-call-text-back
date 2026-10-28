"""Loads secrets from the project's .env file, falling back to environment variables.

On the PC, keys come from .env. In GitHub Actions there is no .env; the workflow passes
the repository secrets in as environment variables instead.
"""
import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
KEYS = ("ANTHROPIC_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "ALERT_TO", "LEAD_WEBHOOK_URL",
        "LEAD_WEBHOOK_SECRET")


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key in KEYS:
        if not values.get(key) and os.environ.get(key):
            values[key] = os.environ[key]
    return values


def require(env: dict[str, str], *keys: str) -> None:
    missing = [k for k in keys if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing keys (set them in .env or as environment variables): {', '.join(missing)}")
