"""``tempo issues``: find Jira issues to log time on."""

from __future__ import annotations

import click

from tempo_cli import validation, views
from tempo_cli.commands._common import pass_app
from tempo_cli.context import AppContext
from tempo_cli.errors import ValidationError
from tempo_cli.output import col

COLUMNS = [
    col("key", "key"),
    col("status", "status"),
    col("summary", "summary", 70),
]

PRESETS = {
    "assigned": "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
    "recent": "worklogAuthor = currentUser() AND worklogDate >= -14d ORDER BY updated DESC",
    "watching": "watcher = currentUser() AND statusCategory != Done ORDER BY updated DESC",
}


@click.group("issues")
def group() -> None:
    """Jira issues (to find the key to log time on)."""


@group.command("list")
@click.option(
    "--preset",
    type=click.Choice(list(PRESETS)),
    default="assigned",
    show_default=True,
    help="assigned = open issues assigned to you; recent = issues you logged time on in "
    "the last 14 days; watching = open issues you watch.",
)
@click.option("--jql", default=None, help="Custom JQL (overrides --preset).")
@click.option("-q", "--search", "text", default=None, help="Full-text search in issues.")
@click.option("--project", default=None, help="Restrict to a project key.")
@click.option("-n", "--limit", type=click.IntRange(1, 500), default=30, show_default=True)
@pass_app
def list_issues(
    app: AppContext,
    preset: str,
    jql: str | None,
    text: str | None,
    project: str | None,
    limit: int,
) -> None:
    """Find issues: your assigned ones, recently logged ones, or any JQL."""
    if jql:
        query = jql
    elif text or project:
        clauses = []
        if project:
            clauses.append(f"project = {validation.project_key(project)}")
        if text:
            if any(ch in text for ch in '"\\'):
                raise ValidationError("Search text cannot contain quotes or backslashes")
            clauses.append(f'text ~ "{text}"')
        query = " AND ".join(clauses) + " ORDER BY updated DESC"
    else:
        query = PRESETS[preset]
    issues = app.jira("search issues").search(query, limit=limit)
    app.printer.items(
        [i if app.raw else views.issue(i) for i in issues],
        COLUMNS,
        kind="issues",
        extra={"jql": query},
    )


@group.command("get")
@click.argument("issue")
@pass_app
def get_issue(app: AppContext, issue: str) -> None:
    """Show an issue (key or id)."""
    key = issue.strip() if validation.is_issue_id(issue) else validation.issue_key(issue)
    data = app.jira("look up issues").issue(key)
    app.printer.item(data if app.raw else views.issue(data))
