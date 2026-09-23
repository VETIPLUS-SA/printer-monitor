"""Configuration for the Kyocera portal extractor, loaded from environment
variables (and an optional `.env` file). Never log the password.

Supports one or several printers:

* Legacy / default: a single printer configured via `KYOCERA_URL`,
  `KYOCERA_USER`, `KYOCERA_PASSWORD` (name "default").
* Multi-printer: `KYOCERA_PRINTERS=name1,name2,...` plus, for each name,
  `KYOCERA_<NAME>_URL` (required) and optionally `KYOCERA_<NAME>_USER` /
  `KYOCERA_<NAME>_PASSWORD`, which independently fall back to the shared
  `KYOCERA_USER` / `KYOCERA_PASSWORD` when not set for that printer.

See README.md for the full `.env` format and examples.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent

DEFAULT_OUTDIR = "output"
DEFAULT_DELAY_MS = 700
DEFAULT_TIMEOUT_MS = 20000
DEFAULT_PRINTER_NAME = "default"

# Printer names in KYOCERA_PRINTERS: letters, digits, underscore only. The
# env var prefix for a printer is KYOCERA_<NAME UPPER>_.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    url: str
    user: str
    password: str
    name: str = DEFAULT_PRINTER_NAME
    outdir: str = DEFAULT_OUTDIR
    delay_ms: int = DEFAULT_DELAY_MS
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    def __repr__(self) -> str:  # never leak the password in logs/repr
        return (
            f"Settings(name={self.name!r}, url={self.url!r}, user={self.user!r}, password='***', "
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


def _shared_settings(env: Mapping[str, str]) -> dict:
    """Settings shared by every printer: output directory, delay, timeout."""
    outdir = env.get("KYOCERA_OUTDIR", DEFAULT_OUTDIR)

    try:
        delay_ms = int(env.get("KYOCERA_DELAY_MS", DEFAULT_DELAY_MS))
    except ValueError as exc:
        raise ConfigError(f"KYOCERA_DELAY_MS must be an integer: {exc}") from exc

    try:
        timeout_ms = int(env.get("KYOCERA_TIMEOUT_MS", DEFAULT_TIMEOUT_MS))
    except ValueError as exc:
        raise ConfigError(f"KYOCERA_TIMEOUT_MS must be an integer: {exc}") from exc

    return {"outdir": outdir, "delay_ms": delay_ms, "timeout_ms": timeout_ms}


def _parse_printer_names(raw: str) -> list[str]:
    """Comma-separated printer names: trimmed, empty entries ignored,
    validated against _NAME_RE, duplicates (case-insensitive) rejected.
    Original casing is preserved for Settings.name."""
    names: list[str] = []
    seen_lower: set[str] = set()
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        if not _NAME_RE.match(name):
            raise ConfigError(
                f"Invalid printer name {name!r} in KYOCERA_PRINTERS: only letters, digits, "
                "and underscores are allowed."
            )
        lower = name.lower()
        if lower in seen_lower:
            raise ConfigError(
                f"Duplicate printer name {name!r} in KYOCERA_PRINTERS (names are case-insensitive)."
            )
        seen_lower.add(lower)
        names.append(name)
    return names


def _printer_settings(name: str, env: Mapping[str, str], shared: dict) -> Settings:
    """Build one printer's Settings, falling back independently to the
    shared KYOCERA_USER / KYOCERA_PASSWORD for that printer's user/password
    when its own KYOCERA_<NAME>_USER / KYOCERA_<NAME>_PASSWORD is not set."""
    prefix = f"KYOCERA_{name.upper()}_"
    url = env.get(f"{prefix}URL")
    user = env.get(f"{prefix}USER") or env.get("KYOCERA_USER")
    password = env.get(f"{prefix}PASSWORD") or env.get("KYOCERA_PASSWORD")

    missing = []
    if not url:
        missing.append(f"{prefix}URL")
    if not user:
        missing.append(f"{prefix}USER (or shared KYOCERA_USER)")
    if not password:
        missing.append(f"{prefix}PASSWORD (or shared KYOCERA_PASSWORD)")
    if missing:
        raise ConfigError(
            f"Printer {name!r}: missing required configuration: {', '.join(missing)}."
        )

    return Settings(url=url, user=user, password=password, name=name, **shared)


def load_printers(
    env: Optional[Mapping[str, str]] = None, load_dotenv_files: bool = True
) -> list[Settings]:
    """Build one Settings per configured printer.

    When `env` is None, reads from `os.environ`, optionally loading `.env`
    files first (when `load_dotenv_files` is True -- the normal CLI path).
    Passing an explicit `env` mapping (e.g. in tests) always skips both
    `.env` loading and `os.environ`, so tests never touch the real `.env`.

    Legacy single-printer mode (KYOCERA_PRINTERS unset/empty): identical
    behavior to before, a single printer named "default" built from
    KYOCERA_URL/KYOCERA_USER/KYOCERA_PASSWORD.

    Multi-printer mode (KYOCERA_PRINTERS set): one Settings per name, in
    the order listed. Every printer is validated; if any is invalid, a
    single ConfigError listing all problems is raised before returning
    anything, so a config error is caught before any network work starts.
    """
    if env is None:
        if load_dotenv_files:
            _load_env_files()
        env = os.environ

    shared = _shared_settings(env)

    raw_names = (env.get("KYOCERA_PRINTERS") or "").strip()
    if not raw_names:
        url = env.get("KYOCERA_URL")
        user = env.get("KYOCERA_USER")
        password = env.get("KYOCERA_PASSWORD")

        missing = [
            var_name
            for var_name, value in (
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
        return [
            Settings(url=url, user=user, password=password, name=DEFAULT_PRINTER_NAME, **shared)
        ]

    names = _parse_printer_names(raw_names)
    if not names:
        raise ConfigError("KYOCERA_PRINTERS is set but contains no valid printer names.")

    printers: list[Settings] = []
    errors: list[str] = []
    for name in names:
        try:
            printers.append(_printer_settings(name, env, shared))
        except ConfigError as exc:
            errors.append(str(exc))

    if errors:
        raise ConfigError(" | ".join(errors))

    return printers
