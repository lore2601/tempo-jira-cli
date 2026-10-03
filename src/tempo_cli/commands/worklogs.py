"""``tempo worklogs``: list, inspect, update and delete worklogs."""

from __future__ import annotations

from typing import Any

import click

from tempo_cli import validation, views
from tempo_cli.commands._common import (
    date_range,
    limit_option,
    pass_app,
    range_options,
    write_options,
)
from tempo_cli.context import AppContext, IssueRef
from tempo_cli.output import col
from tempo_cli.validation import format_duration, hours
from tempo_cli.worklog_plan import (
    PlannedWorklog,
    check_against_existing,
    check_author,
    check_date,
    check_project,
)

COLUMNS = [
    col("id", "id"),
    col("date", "date"),
    col("issue", "issue"),
    col("duration", "duration"),
    col("description", "description", 50),
    col("summary", "summary", 40),
]


@click.group("worklogs")
def group() -> None:
    """Your Tempo worklogs."""


@group.command("list")
@range_options("week")
@click.option("-i", "--issue", "issues", multiple=True, help="Only this issue. Repeatable.")
@click.option("--project", "projects", multiple=True, help="Only this project key. Repeatable.")
@click.option(
    "-u",
    "--user",
    default="me",
    show_default=True,
    help="'me', an Atlassian account id, or 'all' (everyone you may see).",
)
@click.option("--updated-since", default=None, help="Only worklogs updated since this date.")
@limit_option(500)
@pass_app
def list_worklogs(
    app: AppContext,
    period: str | None,
    date_from: str | None,
    date_to: str | None,
    issues: tuple[str, ...],
    projects: tuple[str, ...],
    user: str,
    updated_since: str | None,
    limit: int,
    fetch_all: bool,
) -> None:
    """List worklogs in a period (default: your worklogs this week)."""
    rng = date_range(period, date_from, date_to, "week")
    authors = [] if user == "all" else [app.author(user)]
    issue_ids = [app.resolve_issue(i).id for i in issues]
    project_ids = [
        int(app.jira("resolve project keys").project(validation.project_key(p))["id"])
        for p in projects
    ]
    page = app.tempo.search_worklogs(
        date_from=rng.start.isoformat(),
        date_to=rng.end.isoformat(),
        author_ids=authors,
        issue_ids=issue_ids,
        project_ids=project_ids,
        updated_from=validation.parse_date(updated_since).isoformat() if updated_since else None,
        limit=None if fetch_all else limit,
    )
    total = sum(int(w.get("timeSpentSeconds") or 0) for w in page.items)
    issue_map = app.issue_map(page.items)
    rows = [w if app.raw else views.worklog(w, issue_map) for w in page.items]
    app.printer.items(
        rows,
        COLUMNS,
        kind="worklogs",
        more=page.has_more,
        extra={
            "from": rng.start.isoformat(),
            "to": rng.end.isoformat(),
            "count": len(rows),
            "totalSeconds": total,
            "total": format_duration(total),
            "totalHours": hours(total),
        },
    )


@group.command("get")
@click.argument("worklog_id")
@pass_app
def get_worklog(app: AppContext, worklog_id: str) -> None:
    """Show one worklog by its Tempo id."""
    worklog = app.tempo.get_worklog(validation.worklog_id(worklog_id))
    app.printer.item(worklog if app.raw else views.worklog(worklog, app.issue_map([worklog])))


def _issue_of(app: AppContext, worklog: dict[str, Any]) -> IssueRef:
    issue_id = int((worklog.get("issue") or {}).get("id") or 0)
    if app.has_jira:
        return app.resolve_issue(str(issue_id))
    return IssueRef(id=issue_id)


@group.command("update")
@click.argument("worklog_id")
@click.option("--duration", default=None, help="New time spent, e.g. 2h.")
@click.option("-d", "--date", "day", default=None, help="New date.")
@click.option("-s", "--start", default=None, help="New start time HH:MM.")
@click.option("-m", "--description", default=None, help="New description.")
@click.option("--billable", default=None, help="New billable time.")
@click.option("--remaining", default=None, help="New remaining estimate.")
@click.option(
    "-a",
    "--attr",
    "attributes",
    multiple=True,
    metavar="KEY=VALUE",
    help="Set a work attribute (other attributes are kept). Repeatable.",
)
@write_options
@pass_app
def update(
    app: AppContext,
    worklog_id: str,
    duration: str | None,
    day: str | None,
    start: str | None,
    description: str | None,
    billable: str | None,
    remaining: str | None,
    attributes: tuple[str, ...],
    yes: bool,
    dry_run: bool,
) -> None:
    """Change fields of a worklog; everything not given is kept."""
    app.policy.require_writable()
    wid = validation.worklog_id(worklog_id)
    current = app.tempo.get_worklog(wid)
    author = str((current.get("author") or {}).get("accountId") or app.me())
    check_author(app, author)
    issue = _issue_of(app, current)
    check_project(app, issue)

    old_seconds = int(current.get("timeSpentSeconds") or 0)
    seconds = validation.parse_duration(duration) if duration else old_seconds
    app.policy.require_worklog_length(seconds)
    new_day = validation.parse_date(day) if day else None
    if new_day:
        check_date(app, new_day)

    attrs = {
        a["key"]: a.get("value")
        for a in (current.get("attributes") or {}).get("values") or []
        if a.get("key")
    }
    for key, value in (validation.attribute(a) for a in attributes):
        attrs[key] = value

    body: dict[str, Any] = {
        "authorAccountId": author,
        "startDate": new_day.isoformat() if new_day else current.get("startDate"),
        "timeSpentSeconds": seconds,
    }
    start_time = validation.parse_time(start) if start else current.get("startTime")
    if start_time:
        body["startTime"] = start_time
    desc = description if description is not None else current.get("description")
    if desc:
        body["description"] = validation.description(desc)
    old_billable = current.get("billableSeconds")
    if billable is not None:
        body["billableSeconds"] = validation.parse_duration(billable, allow_zero=True)
    elif old_billable is not None:
        # Keep billable in step with the duration when it used to match it.
        body["billableSeconds"] = seconds if old_billable == old_seconds else old_billable
    if remaining is not None:
        body["remainingEstimateSeconds"] = validation.parse_duration(remaining, allow_zero=True)
    if attrs:
        body["attributes"] = [{"key": k, "value": v} for k, v in attrs.items()]

    if seconds != old_seconds or new_day:
        planned = PlannedWorklog(issue=issue, body=body)
        check_against_existing(
            app, [planned], allow_duplicates=True, exclude_id=current.get("tempoWorklogId")
        )

    changes = []
    if seconds != old_seconds:
        changes.append(f"duration {format_duration(old_seconds)} → {format_duration(seconds)}")
    if body["startDate"] != current.get("startDate"):
        changes.append(f"date {current.get('startDate')} → {body['startDate']}")
    if desc != current.get("description"):
        changes.append(f'description → "{desc}"')
    if start:
        changes.append(f"start → {start_time}")
    if attributes:
        changes.append("attributes")
    if billable is not None or remaining is not None:
        changes.append("billable/remaining")
    summary = f"Update worklog {wid} on {issue.label()}: " + (", ".join(changes) or "no changes")
    request = {"method": "PUT", "path": f"/worklogs/{wid}", "body": body}
    if app.guard_write(
        action="worklogs.update", request=request, yes=yes, dry_run=dry_run, summary=summary
    ):
        updated = app.tempo.update_worklog(wid, body)
        app.printer.item(updated if app.raw else views.worklog(updated, app.issue_map([updated])))


@group.command("delete")
@click.argument("worklog_id")
@write_options
@pass_app
def delete(app: AppContext, worklog_id: str, yes: bool, dry_run: bool) -> None:
    """Delete a worklog."""
    app.policy.require_writable()
    wid = validation.worklog_id(worklog_id)
    current = app.tempo.get_worklog(wid)
    check_author(app, str((current.get("author") or {}).get("accountId") or app.me()))
    issue = _issue_of(app, current)
    check_project(app, issue)
    summary = (
        f"Delete worklog {wid}: {format_duration(current.get('timeSpentSeconds'))} on "
        f"{issue.label()} ({current.get('startDate')})"
    )
    request = {"method": "DELETE", "path": f"/worklogs/{wid}"}
    if app.guard_write(
        action="worklogs.delete", request=request, yes=yes, dry_run=dry_run, summary=summary
    ):
        app.tempo.delete_worklog(wid)
        app.printer.item({"deleted": int(wid)})
