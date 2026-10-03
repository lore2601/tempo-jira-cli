"""``tempo log`` and ``tempo log-batch``: create worklogs."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

import click

from tempo_cli import views
from tempo_cli.commands._common import pass_app, write_options
from tempo_cli.context import AppContext
from tempo_cli.errors import PartialFailure, TempoCliError, ValidationError
from tempo_cli.validation import format_duration
from tempo_cli.worklog_plan import WorklogEntry, check_against_existing, plan

MAX_BATCH = 200


def _entry_options(fn: Any) -> Any:
    fn = click.option(
        "--allow-duplicate", is_flag=True, help="Log even if an identical worklog already exists."
    )(fn)
    fn = click.option(
        "--author", default=None, metavar="ACCOUNT_ID", help="Log for another user (policy-gated)."
    )(fn)
    fn = click.option(
        "-a",
        "--attr",
        "attributes",
        multiple=True,
        metavar="KEY=VALUE",
        help="Work attribute (see `tempo attributes list`). Repeatable.",
    )(fn)
    fn = click.option("--remaining", default=None, help="New remaining estimate, e.g. 2h.")(fn)
    fn = click.option("--billable", default=None, help="Billable time if different, e.g. 1h.")(fn)
    fn = click.option("-m", "--description", default=None, help="Worklog description.")(fn)
    fn = click.option(
        "-s", "--start", default=None, help="Start time HH:MM (default: config start_time)."
    )(fn)
    fn = click.option(
        "-d",
        "--date",
        "day",
        default="today",
        show_default=True,
        help="YYYY-MM-DD, today, yesterday, -2d or a weekday name.",
    )(fn)
    return fn


@click.command("log")
@click.argument("issue")
@click.argument("duration")
@_entry_options
@write_options
@pass_app
def group(
    app: AppContext,
    issue: str,
    duration: str,
    day: str,
    start: str | None,
    description: str | None,
    billable: str | None,
    remaining: str | None,
    attributes: tuple[str, ...],
    author: str | None,
    allow_duplicate: bool,
    yes: bool,
    dry_run: bool,
) -> None:
    """Log DURATION on ISSUE (e.g. `tempo log PROJ-123 1h30m -m "Review" --yes`).

    \b
    DURATION: 1h30m, 1.5h, 90m or 1:30.
    ISSUE:    a Jira key (PROJ-123) or a numeric issue id.
    """
    entry = WorklogEntry(
        issue=issue,
        duration=duration,
        date=day,
        start=start,
        description=description,
        billable=billable,
        remaining=remaining,
        attributes=list(attributes),
        author=author,
    )
    planned = plan(app, entry)
    check_against_existing(app, [planned], allow_duplicates=allow_duplicate)
    request = {"method": "POST", "path": "/worklogs", "body": planned.body}
    if app.guard_write(
        action="worklogs.create",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=planned.summary(),
    ):
        created = app.tempo.create_worklog(planned.body)
        issues = {
            str(planned.issue.id): {
                "key": planned.issue.key,
                "fields": {"summary": planned.issue.summary},
            }
        }
        app.printer.item(created if app.raw else views.worklog(created, issues))


def _read_entries(source: str) -> list[dict[str, Any]]:
    if source == "-":
        text = sys.stdin.read()
        is_csv = not text.lstrip().startswith(("[", "{"))
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"Cannot read {source}: {exc}") from exc
        is_csv = path.suffix.lower() == ".csv"
    if is_csv:
        rows = list(csv.DictReader(io.StringIO(text)))
        entries: list[dict[str, Any]] = []
        for row in rows:
            clean = {k.strip(): v.strip() for k, v in row.items() if k and v and v.strip()}
            if "attributes" in clean:
                clean["attributes"] = [a for a in clean["attributes"].split(";") if a]
            entries.append(clean)
        return entries
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("worklogs", [data])
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise ValidationError("Expected a JSON array of worklog objects")
    return data


@click.command("log-batch")
@click.argument("source")
@click.option("--allow-duplicate", is_flag=True, help="Do not refuse identical worklogs.")
@write_options
@pass_app
def batch(app: AppContext, source: str, allow_duplicate: bool, yes: bool, dry_run: bool) -> None:
    """Log many worklogs from a JSON or CSV file (or '-' for stdin).

    \b
    JSON: [{"issue": "PROJ-1", "duration": "2h", "date": "monday",
            "start": "09:00", "description": "...", "attributes": {"_Role_": "Dev"}}]
    CSV:  issue,duration,date,start,description   (attributes as K=V;K2=V2)

    Every entry is validated, and checked against the daily limit and duplicates,
    before anything is written.
    """
    raw_entries = _read_entries(source)
    if not raw_entries:
        raise ValidationError("No worklogs to log")
    if len(raw_entries) > MAX_BATCH:
        raise ValidationError(f"At most {MAX_BATCH} worklogs per batch")
    planned = []
    for index, data in enumerate(raw_entries, start=1):
        try:
            planned.append(plan(app, WorklogEntry.from_mapping(data, index)))
        except TempoCliError as exc:
            exc.message = f"Entry {index}: {exc.message}"
            raise
    check_against_existing(app, planned, allow_duplicates=allow_duplicate)
    total = sum(p.seconds for p in planned)
    summary = "\n".join(f"  {p.summary()}" for p in planned)
    summary = f"Create {len(planned)} worklogs ({format_duration(total)} total):\n{summary}"
    request = {"method": "POST", "path": "/worklogs", "bodies": [p.body for p in planned]}
    if not app.guard_write(
        action="worklogs.create-batch", request=request, yes=yes, dry_run=dry_run, summary=summary
    ):
        return
    results: list[dict[str, Any]] = []
    failed = 0
    for index, p in enumerate(planned, start=1):
        try:
            created = app.tempo.create_worklog(p.body)
            results.append(
                {
                    "entry": index,
                    "ok": True,
                    "id": created.get("tempoWorklogId"),
                    "issue": p.issue.label(),
                    "date": p.day,
                    "duration": format_duration(p.seconds),
                }
            )
        except TempoCliError as exc:
            failed += 1
            results.append(
                {
                    "entry": index,
                    "ok": False,
                    "issue": p.issue.label(),
                    "date": p.day,
                    "error": exc.message,
                }
            )
    app.printer.item({"created": len(planned) - failed, "failed": failed, "results": results})
    if failed:
        raise PartialFailure(
            f"{failed} of {len(planned)} worklogs failed",
            hint="See the results above; successful entries were created.",
        )
