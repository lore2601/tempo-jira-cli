"""``tempo summary``: logged vs required time, per day or per issue."""

from __future__ import annotations

from typing import Any

import click

from tempo_cli.commands._common import date_range, pass_app, range_options
from tempo_cli.context import AppContext
from tempo_cli.output import col
from tempo_cli.validation import format_duration, hours

DAY_COLUMNS = [
    col("date", "date"),
    col("day", "weekday"),
    col("type", "type"),
    col("required", "required"),
    col("logged", "logged"),
    col("missing", "missing"),
]
ISSUE_COLUMNS = [
    col("issue", "issue"),
    col("logged", "logged"),
    col("hours", "hours"),
    col("worklogs", "worklogs"),
    col("summary", "summary", 50),
]


@click.command("summary")
@range_options("week")
@click.option(
    "--by",
    type=click.Choice(["day", "issue"]),
    default="day",
    show_default=True,
    help="Group by day (with required hours) or by issue.",
)
@pass_app
def group(
    app: AppContext, period: str | None, date_from: str | None, date_to: str | None, by: str
) -> None:
    """Show how much you logged, and what is still missing, in a period.

    \b
    tempo summary                      # this week, per day, with missing hours
    tempo summary -p last-month --by issue
    """
    rng = date_range(period, date_from, date_to, "week")
    me = app.me()
    worklogs = app.tempo.search_worklogs(
        date_from=rng.start.isoformat(), date_to=rng.end.isoformat(), author_ids=[me]
    ).items
    logged_total = sum(int(w.get("timeSpentSeconds") or 0) for w in worklogs)
    base: dict[str, Any] = {
        "from": rng.start.isoformat(),
        "to": rng.end.isoformat(),
        "loggedSeconds": logged_total,
        "logged": format_duration(logged_total),
    }

    if by == "issue":
        per_issue: dict[str, dict[str, Any]] = {}
        issue_map = app.issue_map(worklogs)
        for w in worklogs:
            issue_id = str((w.get("issue") or {}).get("id"))
            issue = issue_map.get(issue_id) or {}
            row = per_issue.setdefault(
                issue_id,
                {
                    "issue": issue.get("key") or issue_id,
                    "summary": (issue.get("fields") or {}).get("summary"),
                    "seconds": 0,
                    "worklogs": 0,
                },
            )
            row["seconds"] += int(w.get("timeSpentSeconds") or 0)
            row["worklogs"] += 1
        rows = sorted(per_issue.values(), key=lambda r: -int(r["seconds"]))
        for row in rows:
            row["logged"] = format_duration(row["seconds"])
            row["hours"] = hours(row["seconds"])
        app.printer.items(rows, ISSUE_COLUMNS, kind="issues", extra=base)
        return

    schedule = {
        s.get("date"): s
        for s in app.tempo.user_schedule(rng.start.isoformat(), rng.end.isoformat())
    }
    logged: dict[str, int] = {}
    for w in worklogs:
        start = str(w.get("startDate"))
        logged[start] = logged.get(start, 0) + int(w.get("timeSpentSeconds") or 0)

    rows = []
    required_total = missing_total = 0
    for day in rng.days():
        key = day.isoformat()
        info = schedule.get(key) or {}
        required = int(info.get("requiredSeconds") or 0)
        done = logged.get(key, 0)
        missing = max(required - done, 0)
        required_total += required
        missing_total += missing
        rows.append(
            {
                "date": key,
                "weekday": day.strftime("%a"),
                "type": info.get("type"),
                "holiday": (info.get("holiday") or {}).get("name"),
                "requiredSeconds": required,
                "loggedSeconds": done,
                "missingSeconds": missing,
                "required": format_duration(required),
                "logged": format_duration(done),
                "missing": format_duration(missing) if missing else "",
            }
        )
    base.update(
        {
            "requiredSeconds": required_total,
            "required": format_duration(required_total),
            "missingSeconds": missing_total,
            "missing": format_duration(missing_total),
            "daysMissing": [r["date"] for r in rows if r["missingSeconds"]],
        }
    )
    app.printer.items(rows, DAY_COLUMNS, kind="days", extra=base)
