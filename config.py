"""Validated settings loaded from environment variables.

Fails early with a clear ConfigError when required configuration is missing or invalid.
Secrets (the seed phrase) are never logged or included in error messages.
"""
import os
from dataclasses import dataclass
from typing import Mapping, Optional


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    agent_name: str
    agent_seed_phrase: str      # secret - do not log
    agent_port: int
    agent_mailbox: bool
    log_level: str
    max_drones: int
    max_ticks_per_request: int
    run_time_budget_seconds: float
    max_sessions: int
    session_ttl_seconds: int
    max_message_chars: int

    def __repr__(self) -> str:  # keep the seed phrase out of accidental logs
        return f"Settings(agent_name={self.agent_name!r}, port={self.agent_port}, mailbox={self.agent_mailbox})"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is optional at runtime (e.g. on a hosting platform)
        return
    load_dotenv()


def _int(env: Mapping[str, str], key: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{key} must be between {lo} and {hi}, got {value}")
    return value


def _float(env: Mapping[str, str], key: str, default: float, lo: float, hi: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{key} must be between {lo} and {hi}, got {value}")
    return value


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be true or false, got {raw!r}")


def load_settings(env: Optional[Mapping[str, str]] = None, use_dotenv: bool = True) -> Settings:
    """Build Settings from `env` (defaults to os.environ, after loading a local .env)."""
    if env is None:
        if use_dotenv:
            _load_dotenv()
        env = os.environ

    seed = env.get("AGENT_SEED_PHRASE", "").strip()
    if not seed:
        raise ConfigError(
            "AGENT_SEED_PHRASE is required (copy .env.example to .env and set a long, "
            "private phrase). It determines the agent's address."
        )
    if len(seed) < 12:
        raise ConfigError("AGENT_SEED_PHRASE is too short; use at least 12 characters.")

    level = env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(f"LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, got {level!r}")

    return Settings(
        agent_name=env.get("AGENT_NAME", "").strip() or "agri-swarm-agent",
        agent_seed_phrase=seed,
        agent_port=_int(env, "AGENT_PORT", 8000, 1024, 65535),
        agent_mailbox=_bool(env, "AGENT_MAILBOX", True),
        log_level=level,
        max_drones=_int(env, "MAX_DRONES", 200, 1, 500),
        max_ticks_per_request=_int(env, "MAX_TICKS_PER_REQUEST", 500, 1, 5000),
        run_time_budget_seconds=_float(env, "RUN_TIME_BUDGET_SECONDS", 5.0, 0.5, 60.0),
        max_sessions=_int(env, "MAX_SESSIONS", 100, 1, 10000),
        session_ttl_seconds=_int(env, "SESSION_TTL_SECONDS", 3600, 60, 604800),
        max_message_chars=_int(env, "MAX_MESSAGE_CHARS", 500, 20, 5000),
    )
