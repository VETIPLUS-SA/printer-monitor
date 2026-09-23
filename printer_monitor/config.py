"""Configuration for the Kyocera portal extractor, loaded from environment
variables (and an optional `.env` file). Never log the password.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent

DEFAULT_OUTDIR = "output"
DEFAULT_DELAY_MS = 700
DEFAULT_TIMEOUT_MS = 20000


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    url: str
    user: str
    password: str
    outdir: str = DEFAULT_OUTDIR
    delay_ms: int = DEFAULT_DELAY_MS
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    def __repr__(self) -> str:  # never leak the password in logs/repr
        return (
            f"Settings(url={self.url!r}, user={self.user!r}, password='***', "
            f"outdir={self.outdir!r}, delay_ms={self.delay_ms}, timeout_ms={self.timeout_ms})"
        )


def _load_env_files() -> None:
    """Load the project-root `.env` first, then the current working
    directory's `.env` (which never overrides already-set variables), so
    `main.py` works the same whether it's run from the repo root or
    elsewhere. Real environment variables always take precedence over
    either file.
    """
    root_env = _PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=root_env, override=False)
    load_dotenv(override=False)  # .env in the current working directory, if any


def load_settings() -> Settings:
    """Build Settings from environment variables, raising ConfigError if a
    required one is missing."""
    _load_env_files()

    url = os.environ.get("KYOCERA_URL")
    user = os.environ.get("KYOCERA_USER")
    password = os.environ.get("KYOCERA_PASSWORD")

    missing = [
        name
        for name, value in (
            ("KYOCERA_URL", url),
            ("KYOCERA_USER", user),
            ("KYOCERA_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in (see README.md)."
        )

    outdir = os.environ.get("KYOCERA_OUTDIR", DEFAULT_OUTDIR)

    try:
        delay_ms = int(os.environ.get("KYOCERA_DELAY_MS", DEFAULT_DELAY_MS))
    except ValueError as exc:
        raise ConfigError(f"KYOCERA_DELAY_MS must be an integer: {exc}") from exc

    try:
        timeout_ms = int(os.environ.get("KYOCERA_TIMEOUT_MS", DEFAULT_TIMEOUT_MS))
    except ValueError as exc:
        raise ConfigError(f"KYOCERA_TIMEOUT_MS must be an integer: {exc}") from exc

    return Settings(
        url=url,
        user=user,
        password=password,
        outdir=outdir,
        delay_ms=delay_ms,
        timeout_ms=timeout_ms,
    )
