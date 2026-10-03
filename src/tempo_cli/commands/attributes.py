"""``tempo attributes``: work attributes configured in Tempo."""

from __future__ import annotations

import click

from tempo_cli import views
from tempo_cli.commands._common import pass_app
from tempo_cli.context import AppContext
from tempo_cli.output import col

COLUMNS = [
    col("key", "key"),
    col("name", "name", 30),
    col("type", "type"),
    col("required", "required"),
    col("values", "values", 60),
]


@click.group("attributes")
def group() -> None:
    """Work attributes (custom worklog fields such as Role or Billable)."""


@group.command("list")
@click.option("--required", "only_required", is_flag=True, help="Only required attributes.")
@pass_app
def list_attributes(app: AppContext, only_required: bool) -> None:
    """List work attributes and their allowed values (use them with `tempo log -a KEY=VALUE`)."""
    items = app.tempo.work_attributes()
    if only_required:
        items = [a for a in items if a.get("required")]
    app.printer.items(
        [a if app.raw else views.work_attribute(a) for a in items], COLUMNS, kind="attributes"
    )
