"""Paths, configuration file and the local safety policy.

.. code-block:: toml

    # ~/.config/tempo-cli/config.toml
    [defaults]
    format = "auto"
    start_time = "09:00"

    [policy]
    read_only = false
    projects = ["*"]              # projects you may log time on
    max_worklog_hours = 12        # refuse a single worklog longer than this
    max_daily_hours = 14          # refuse if the day's total would exceed this
    allow_future_dates = false    # refuse worklogs dated after today
    allow_other_authors = false   # refuse logging time for someone else

Environment variables override the file: ``TEMPO_READ_ONLY``,
``TEMPO_ALLOW_PROJECTS``, ``TEMPO_MAX_WORKLOG_HOURS``, ``TEMPO_MAX_DAILY_HOURS``,
``TEMPO_ALLOW_FUTURE_DATES`` and ``TEMPO_ALLOW_OTHER_AUTHORS``.
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tempo_cli.errors import PolicyError, ValidationError

APP_NAME = "tempo-cli"
WILDCARD = "*"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TEMPO_CONFIG_DIR"):
        return Path(env["TEMPO_CONFIG_DIR"]).expanduser()
    if sys.platform == "win32" and env.get("APPDATA"):  # pragma: no cover - platform specific
        return Path(env["APPDATA"]) / APP_NAME
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / APP_NAME


def config_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TEMPO_CONFIG"):
        return Path(env["TEMPO_CONFIG"]).expanduser()
    return config_dir(env) / "config.toml"


def credentials_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TEMPO_CREDENTIALS_FILE"):
        return Path(env["TEMPO_CREDENTIALS_FILE"]).expanduser()
    return config_dir(env) / "credentials.json"


def parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValidationError(f"{name} must be a boolean, got {value!r}")


def _parse_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a number, got {value!r}") from None
    if not 0 < number <= 24:
        raise ValidationError(f"{name} must be between 0 and 24")
    return number


def _parse_projects(value: Any, name: str) -> frozenset[str]:
    from tempo_cli import validation

    if isinstance(value, str):
        items = [v for v in value.split(",") if v.strip()]
    elif isinstance(value, list):
        items = value
    else:
        raise ValidationError(f"{name} must be a list of project keys")
    return frozenset(
        WILDCARD if str(i).strip() == WILDCARD else validation.project_key(str(i)) for i in items
    )


@dataclass(frozen=True)
class Policy:
    read_only: bool = False
    projects: frozenset[str] = field(default_factory=lambda: frozenset({WILDCARD}))
    max_worklog_hours: float = 12.0
    max_daily_hours: float = 14.0
    allow_future_dates: bool = False
    allow_other_authors: bool = False

    def require_writable(self) -> None:
        if self.read_only:
            raise PolicyError(
                "Writes are disabled (read-only mode)",
                hint="Unset TEMPO_READ_ONLY or policy.read_only to allow writes.",
            )

    def require_project(self, project: str) -> None:
        if WILDCARD not in self.projects and project not in self.projects:
            raise PolicyError(
                f"Logging time on project {project} is not allowed by the local policy",
                hint="Add it to policy.projects in the config file or TEMPO_ALLOW_PROJECTS.",
            )

    def require_worklog_length(self, seconds: int) -> None:
        if seconds > self.max_worklog_hours * 3600:
            raise PolicyError(
                f"A single worklog of {seconds / 3600:.2f}h exceeds the limit of "
                f"{self.max_worklog_hours:g}h",
                hint="Split it, or raise policy.max_worklog_hours / TEMPO_MAX_WORKLOG_HOURS.",
            )

    def require_daily_total(self, day: str, total_seconds: int) -> None:
        if total_seconds > self.max_daily_hours * 3600:
            raise PolicyError(
                f"{day} would total {total_seconds / 3600:.2f}h, above the daily limit of "
                f"{self.max_daily_hours:g}h",
                hint="Check for duplicates with `tempo worklogs list`, or raise "
                "policy.max_daily_hours / TEMPO_MAX_DAILY_HOURS.",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "read_only": self.read_only,
            "projects": sorted(self.projects),
            "max_worklog_hours": self.max_worklog_hours,
            "max_daily_hours": self.max_daily_hours,
            "allow_future_dates": self.allow_future_dates,
            "allow_other_authors": self.allow_other_authors,
        }


@dataclass(frozen=True)
class Config:
    policy: Policy = field(default_factory=Policy)
    defaults: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None


_POLICY_KEYS = {
    "read_only",
    "projects",
    "max_worklog_hours",
    "max_daily_hours",
    "allow_future_dates",
    "allow_other_authors",
}


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    path = config_file(env)
    data: dict[str, Any] = {}
    source: Path | None = None
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValidationError(f"Cannot read config file {path}: {exc}") from exc
        source = path

    raw = data.get("policy") or {}
    if not isinstance(raw, dict):
        raise ValidationError("[policy] must be a table")
    unknown = set(raw) - _POLICY_KEYS
    if unknown:
        raise ValidationError(f"Unknown policy keys: {', '.join(sorted(unknown))}")

    values: dict[str, Any] = {
        "read_only": parse_bool(raw.get("read_only", False), "policy.read_only"),
        "projects": _parse_projects(raw.get("projects", [WILDCARD]), "policy.projects"),
        "max_worklog_hours": _parse_number(raw.get("max_worklog_hours", 12), "max_worklog_hours"),
        "max_daily_hours": _parse_number(raw.get("max_daily_hours", 14), "max_daily_hours"),
        "allow_future_dates": parse_bool(
            raw.get("allow_future_dates", False), "allow_future_dates"
        ),
        "allow_other_authors": parse_bool(
            raw.get("allow_other_authors", False), "allow_other_authors"
        ),
    }
    overrides = {
        "TEMPO_READ_ONLY": ("read_only", parse_bool),
        "TEMPO_ALLOW_PROJECTS": ("projects", _parse_projects),
        "TEMPO_MAX_WORKLOG_HOURS": ("max_worklog_hours", _parse_number),
        "TEMPO_MAX_DAILY_HOURS": ("max_daily_hours", _parse_number),
        "TEMPO_ALLOW_FUTURE_DATES": ("allow_future_dates", parse_bool),
        "TEMPO_ALLOW_OTHER_AUTHORS": ("allow_other_authors", parse_bool),
    }
    for var, (key, parser) in overrides.items():
        if var in env:
            values[key] = parser(env[var], var)

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValidationError("[defaults] must be a table")
    return Config(policy=Policy(**values), defaults=defaults, source=source)


SAMPLE_CONFIG = """\
# tempo-cli configuration. Environment variables take precedence over this file.

[defaults]
# Output format when --format is not given: auto | json | ndjson | table
# format = "auto"
# Default start time for new worklogs (HH:MM). Tempo uses 00:00 when omitted.
# start_time = "09:00"

[policy]
# Refuse every write (log, update, delete, submit).
read_only = false
# Projects you may log time on. "*" means any project.
projects = ["*"]
# Refuse a single worklog longer than this many hours.
max_worklog_hours = 12
# Refuse a worklog if your total for that day would exceed this many hours.
max_daily_hours = 14
# Refuse worklogs dated in the future.
allow_future_dates = false
# Refuse logging time on behalf of other users (--author).
allow_other_authors = false
"""
