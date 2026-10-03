"""``tempo accounts``: Tempo accounts (cost centres / customers)."""

from __future__ import annotations

import click

from tempo_cli import views
from tempo_cli.commands._common import limit_option, pass_app
from tempo_cli.context import AppContext
from tempo_cli.output import col

COLUMNS = [
    col("key", "key"),
    col("name", "name", 40),
    col("status", "status"),
    col("customer", "customer", 30),
]


@click.group("accounts")
def group() -> None:
    """Tempo accounts."""


@group.command("list")
@click.option(
    "--status",
    type=click.Choice(["OPEN", "CLOSED", "ARCHIVED", "all"], case_sensitive=False),
    default="OPEN",
    show_default=True,
)
@limit_option(200)
@pass_app
def list_accounts(app: AppContext, status: str, limit: int, fetch_all: bool) -> None:
    """List Tempo accounts (for the account work attribute, if your instance uses one)."""
    page = app.tempo.accounts(limit=None if fetch_all else limit)
    items = page.items
    if status.lower() != "all":
        items = [a for a in items if str(a.get("status", "")).upper() == status.upper()]
    app.printer.items(
        [a if app.raw else views.account(a) for a in items],
        COLUMNS,
        kind="accounts",
        more=page.has_more,
    )
