"""``tempo approvals``: timesheet periods, approval status and submission."""

from __future__ import annotations

import click

from tempo_cli import validation, views
from tempo_cli.commands._common import date_range, pass_app, range_options, write_options
from tempo_cli.context import AppContext
from tempo_cli.output import col

PERIOD_COLUMNS = [col("from", "from"), col("to", "to")]
REVIEWER_COLUMNS = [col("account id", "accountId")]


@click.group("approvals")
def group() -> None:
    """Timesheet approval periods, status and submission."""


@group.command("periods")
@range_options("month")
@pass_app
def periods(
    app: AppContext, period: str | None, date_from: str | None, date_to: str | None
) -> None:
    """List approval periods overlapping a date range (default: this month)."""
    rng = date_range(period, date_from, date_to, "month")
    items = app.tempo.periods(rng.start.isoformat(), rng.end.isoformat())
    app.printer.items(items, PERIOD_COLUMNS, kind="periods")


@group.command("status")
@click.option(
    "-d",
    "--date",
    "day",
    default="today",
    show_default=True,
    help="Any date inside the period to check.",
)
@pass_app
def status(app: AppContext, day: str) -> None:
    """Show your timesheet approval status for the period containing DATE."""
    when = validation.parse_date(day).isoformat()
    data = app.tempo.approval(app.me(), when, None)
    app.printer.item(data if app.raw else views.approval(data))


@group.command("reviewers")
@pass_app
def reviewers(app: AppContext) -> None:
    """List who can review your timesheet."""
    items = app.tempo.approval_reviewers(app.me())
    app.printer.items(items, REVIEWER_COLUMNS, kind="reviewers")


@group.command("submit")
@click.option(
    "-d",
    "--date",
    "day",
    default="today",
    show_default=True,
    help="Any date inside the period to submit.",
)
@click.option("--reviewer", default=None, metavar="ACCOUNT_ID", help="Reviewer account id.")
@click.option("--comment", default=None, help="Comment for the reviewer.")
@write_options
@pass_app
def submit(
    app: AppContext,
    day: str,
    reviewer: str | None,
    comment: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Submit your timesheet for approval."""
    when = validation.parse_date(day).isoformat()
    body: dict[str, str] = {}
    if reviewer:
        body["reviewerAccountId"] = validation.account_id(reviewer)
    if comment:
        body["comment"] = validation.description(comment)
    me = app.me()
    request = {
        "method": "POST",
        "path": f"/timesheet-approvals/user/{me}/submit",
        "params": {"from": when},
        "body": body,
    }
    current = None if dry_run else app.tempo.approval(me, when, None)
    summary = f"Submit your timesheet for the period containing {when}"
    if current:
        view = views.approval(current)
        summary = (
            f"Submit timesheet {view.get('from')} → {view.get('to')}: logged "
            f"{view.get('logged') or '0m'} of {view.get('required') or '0m'} required"
        )
    if app.guard_write(
        action="approvals.submit", request=request, yes=yes, dry_run=dry_run, summary=summary
    ):
        result = app.tempo.submit_approval(me, when, None, body)
        app.printer.item(result if app.raw else views.approval(result))
