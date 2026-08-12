from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import UTC, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from deezync.domain.account import DeezerAccount

DEFAULT_INDEX = "deezer-history"
DEFAULT_USERS_FILE = "users.toml"
DEFAULT_ENV_FILE = ".env"


class ConfigError(RuntimeError):
    """Missing or invalid configuration."""


@dataclass(frozen=True)
class Settings:
    es_url: str
    es_index: str = DEFAULT_INDEX
    es_api_key: str | None = None
    es_username: str | None = None
    es_password: str | None = None
    users_file: Path = Path(DEFAULT_USERS_FILE)


def load_settings(
    users_file: str | None = None, env_file: str | Path = DEFAULT_ENV_FILE
) -> Settings:
    """Read configuration from the environment, topped up by the .env of the working directory.

    The file is looked up at that exact location, without walking up the tree: an upward
    search could pick up a .env belonging to another project.
    """
    env_path = Path(env_file)
    if env_path.is_file():
        load_dotenv(env_path)

    es_url = os.getenv("ES_URL")
    if not es_url:
        raise ConfigError("ES_URL is required (see .env.example)")

    api_key = os.getenv("ES_API_KEY")
    username = os.getenv("ES_USERNAME")
    password = os.getenv("ES_PASSWORD")
    if not api_key and not (username and password):
        raise ConfigError(
            "missing Elasticsearch authentication: ES_API_KEY, or ES_USERNAME + ES_PASSWORD"
        )

    return Settings(
        es_url=es_url,
        es_index=os.getenv("ES_INDEX") or DEFAULT_INDEX,
        es_api_key=api_key,
        es_username=username,
        es_password=password,
        users_file=Path(users_file or os.getenv("DEEZYNC_USERS_FILE") or DEFAULT_USERS_FILE),
    )


def load_accounts(path: Path) -> list[DeezerAccount]:
    """Read the list of Deezer accounts from a TOML file.

    `timezone` is required on every account: it is the one thing about a listener
    that no API can answer, and defaulting it silently would produce plausible but
    wrong dayOfWeek and hourOfDay. Everything else Deezer knows -- profile id,
    country -- is read at login rather than declared here.
    """
    if not path.exists():
        raise ConfigError(f"accounts file not found: {path} (copy users.example.toml)")

    content = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_accounts = content.get("accounts") or []
    if not raw_accounts:
        raise ConfigError(f"no account declared in {path} (expected an [[accounts]] block)")

    try:
        accounts = [
            DeezerAccount(
                name=str(item.get("name", "")),
                access_token=_optional_str(item, "access_token"),
                arl=_optional_str(item, "arl"),
                display_timezone=_account_timezone(item),
            )
            for item in raw_accounts
        ]
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    names = [account.name for account in accounts]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ConfigError(f"{path}: duplicate account names: {sorted(duplicates)}")

    return accounts


def _optional_str(item: dict, key: str) -> str | None:
    value = item.get(key)
    return str(value) if value else None


def _account_timezone(item: dict) -> tzinfo:
    name = _optional_str(item, "timezone")
    if name is None:
        raise ValueError(
            f"account {item.get('name')!r}: `timezone` is required, "
            'e.g. timezone = "Europe/Paris" (or "UTC")'
        )
    if name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"account {item.get('name')!r}: invalid timezone {name!r}") from exc
