"""Building and checking worklog requests before they are sent.

All safety checks that apply to creating a worklog live here, so ``tempo log``
and ``tempo log-batch`` behave identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tempo_cli import validation
from tempo_cli.context import AppContext, IssueRef
from tempo_cli.errors import PolicyError, ValidationError
from tempo_cli.validation import format_duration


@dataclass
class WorklogEntry:
    """Raw user input for one worklog."""

    issue: str
    duration: str
    date: str = "today"
    start: str | None = None
    description: str | None = None
    billable: str | None = None
    remaining: str | None = None
    attributes: list[str] = field(default_factory=list)
    author: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any], index: int) -> WorklogEntry:
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValidationError(f"Entry {index}: unknown fields {', '.join(sorted(unknown))}")
        if not data.get("issue") or not data.get("duration"):
            raise ValidationError(f"Entry {index}: 'issue' and 'duration' are required")
        attrs = data.get("attributes") or []
        if isinstance(attrs, dict):
            attrs = [f"{k}={v}" for k, v in attrs.items()]
        return cls(
            issue=str(data["issue"]),
            duration=str(data["duration"]),
            date=str(data.get("date") or "today"),
            start=str(data["start"]) if data.get("start") else None,
            description=str(data["description"]) if data.get("description") else None,
            billable=str(data["billable"]) if data.get("billable") else None,
            remaining=str(data["remaining"]) if data.get("remaining") is not None else None,
            attributes=[str(a) for a in attrs],
            author=str(data["author"]) if data.get("author") else None,
        )


@dataclass
class PlannedWorklog:
    issue: IssueRef
    body: dict[str, Any]

    @property
    def seconds(self) -> int:
        return int(self.body["timeSpentSeconds"])

    @property
    def day(self) -> str:
        return str(self.body["startDate"])

    def summary(self) -> str:
        line = f"Log {format_duration(self.seconds)} on {self.issue.label()}"
        if self.issue.summary:
            line += f" ({self.issue.summary})"
        line += f" for {self.day}"
        if self.body.get("startTime"):
            line += f" at {self.body['startTime'][:5]}"
        if self.body.get("description"):
            line += f': "{self.body["description"]}"'
        return line


def check_date(app: AppContext, day: date) -> None:
    if day > date.today() and not app.policy.allow_future_dates:
        raise PolicyError(
            f"{day.isoformat()} is in the future",
            hint="Set policy.allow_future_dates = true or TEMPO_ALLOW_FUTURE_DATES=1 to allow it.",
        )


def check_author(app: AppContext, author: str) -> None:
    if author != app.me() and not app.policy.allow_other_authors:
        raise PolicyError(
            "Logging time for another user is disabled",
            hint="Set policy.allow_other_authors = true or TEMPO_ALLOW_OTHER_AUTHORS=1.",
        )


def check_project(app: AppContext, issue: IssueRef) -> None:
    if issue.project:
        app.policy.require_project(issue.project)
    elif "*" not in app.policy.projects:
        raise PolicyError(
            f"Cannot verify the project of issue {issue.label()}",
            hint="Configure Jira credentials so the project allowlist can be enforced.",
        )


def plan(app: AppContext, entry: WorklogEntry) -> PlannedWorklog:
    """Validate an entry and apply the static policy checks (no daily-total yet)."""
    app.policy.require_writable()
    seconds = validation.parse_duration(entry.duration)
    day = validation.parse_date(entry.date)
    check_date(app, day)
    app.policy.require_worklog_length(seconds)
    author = app.author(entry.author)
    check_author(app, author)

    body: dict[str, Any] = {
        "authorAccountId": author,
        "startDate": day.isoformat(),
        "timeSpentSeconds": seconds,
    }
    start = entry.start or app.config.defaults.get("start_time")
    if start:
        body["startTime"] = validation.parse_time(str(start))
    if entry.description:
        body["description"] = validation.description(entry.description)
    if entry.billable is not None:
        body["billableSeconds"] = validation.parse_duration(
            entry.billable, what="billable time", allow_zero=True
        )
    if entry.remaining is not None:
        body["remainingEstimateSeconds"] = validation.parse_duration(
            entry.remaining, what="remaining estimate", allow_zero=True
        )
    if entry.attributes:
        pairs = [validation.attribute(a) for a in entry.attributes]
        body["attributes"] = [{"key": k, "value": v} for k, v in pairs]

    issue = app.resolve_issue(entry.issue)
    check_project(app, issue)
    body["issueId"] = issue.id
    return PlannedWorklog(issue=issue, body=body)


def existing_for_days(app: AppContext, author: str, days: set[str]) -> list[dict[str, Any]]:
    if not days:
        return []
    return app.tempo.search_worklogs(
        date_from=min(days), date_to=max(days), author_ids=[author]
    ).items


def check_against_existing(
    app: AppContext,
    planned: list[PlannedWorklog],
    *,
    allow_duplicates: bool,
    exclude_id: int | None = None,
) -> None:
    """Enforce the daily limit and refuse likely duplicates."""
    by_author: dict[str, list[PlannedWorklog]] = {}
    for p in planned:
        by_author.setdefault(str(p.body["authorAccountId"]), []).append(p)
    for author, items in by_author.items():
        existing = [
            w
            for w in existing_for_days(app, author, {p.day for p in items})
            if w.get("tempoWorklogId") != exclude_id
        ]
        totals: dict[str, int] = {}
        for w in existing:
            day = str(w.get("startDate"))
            totals[day] = totals.get(day, 0) + int(w.get("timeSpentSeconds") or 0)
        for p in items:
            if not allow_duplicates:
                for w in existing:
                    if (
                        (w.get("issue") or {}).get("id") == p.issue.id
                        and str(w.get("startDate")) == p.day
                        and int(w.get("timeSpentSeconds") or 0) == p.seconds
                        and (w.get("description") or "") == (p.body.get("description") or "")
                    ):
                        raise PolicyError(
                            f"An identical worklog already exists (id {w.get('tempoWorklogId')})",
                            reason="duplicateWorklog",
                            hint="Pass --allow-duplicate if you really want a second one.",
                            details={"existingWorklogId": w.get("tempoWorklogId")},
                        )
            totals[p.day] = totals.get(p.day, 0) + p.seconds
            app.policy.require_daily_total(p.day, totals[p.day])
