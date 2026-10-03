"""Option decorators shared by command modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import click

from tempo_cli.context import AppContext
from tempo_cli.validation import PERIODS, DateRange, resolve_range

F = TypeVar("F", bound=Callable[..., Any])

pass_app = click.make_pass_decorator(AppContext)


def write_options(fn: F) -> F:
    fn = click.option(
        "--dry-run", is_flag=True, help="Print the request that would be sent and exit."
    )(fn)
    fn = click.option(
        "-y",
        "--yes",
        is_flag=True,
        help="Do not ask for confirmation (required when not on a TTY).",
    )(fn)
    return fn


def range_options(default: str) -> Callable[[F], F]:
    """Add ``--period``, ``--from`` and ``--to``."""

    def decorator(fn: F) -> F:
        fn = click.option("--to", "date_to", default=None, help="End date (inclusive).")(fn)
        fn = click.option(
            "--from",
            "date_from",
            default=None,
            help="Start date: YYYY-MM-DD, today, yesterday, -7d, monday...",
        )(fn)
        fn = click.option(
            "-p",
            "--period",
            type=click.Choice(PERIODS),
            default=None,
            help=f"Named period (default: {default}).",
        )(fn)
        return fn

    return decorator


def date_range(
    period: str | None, date_from: str | None, date_to: str | None, default: str
) -> DateRange:
    return resolve_range(period, date_from, date_to, default=default)


def limit_option(default: int) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        fn = click.option(
            "--all", "fetch_all", is_flag=True, help="Fetch every result (ignores --limit)."
        )(fn)
        fn = click.option(
            "-n",
            "--limit",
            type=click.IntRange(min=1),
            default=default,
            show_default=True,
            help="Maximum number of results.",
        )(fn)
        return fn

    return decorator
