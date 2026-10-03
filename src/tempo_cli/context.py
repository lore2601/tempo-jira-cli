"""Shared state for commands: lazy API clients, identity, issue resolution, write guard."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import click

from tempo_cli import credentials, validation
from tempo_cli.clients import JiraClient, TempoClient
from tempo_cli.config import Config, Policy
from tempo_cli.credentials import Credentials
from tempo_cli.errors import ConfirmationRequired, ValidationError
from tempo_cli.output import Printer


@dataclass
class IssueRef:
    id: int
    key: str | None = None
    project: str | None = None
    summary: str | None = None

    def label(self) -> str:
        return self.key or str(self.id)


@dataclass
class AppContext:
    config: Config
    printer: Printer
    raw: bool = False
    debug: bool = False
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    tempo_factory: Callable[[Credentials], TempoClient] | None = None
    jira_factory: Callable[[Credentials], JiraClient] | None = None
    _creds: Credentials | None = None
    _tempo: TempoClient | None = None
    _jira: JiraClient | None = None
    _me: str | None = None

    @property
    def policy(self) -> Policy:
        return self.config.policy

    @property
    def creds(self) -> Credentials:
        if self._creds is None:
            self._creds = credentials.resolve(self.env)
        return self._creds

    @property
    def tempo(self) -> TempoClient:
        if self._tempo is None:
            token = credentials.require_tempo(self.creds)
            if self.tempo_factory:
                self._tempo = self.tempo_factory(self.creds)
            else:
                self._tempo = TempoClient(token, self.creds.tempo_base_url)
        return self._tempo

    def jira(self, why: str) -> JiraClient:
        if self._jira is None:
            credentials.require_jira(self.creds, why)
            if self.jira_factory:
                self._jira = self.jira_factory(self.creds)
            else:
                self._jira = JiraClient(
                    str(self.creds.jira_url), str(self.creds.jira_email), str(self.creds.jira_token)
                )
        return self._jira

    @property
    def has_jira(self) -> bool:
        return self.jira_factory is not None or self.creds.has_jira

    def me(self) -> str:
        """The current user's Atlassian account id."""
        if self._me is None:
            if self.creds.account_id:
                self._me = self.creds.account_id
            else:
                self._me = str(self.jira("find your Atlassian account id").myself()["accountId"])
        return self._me

    def author(self, value: str | None) -> str:
        if value in (None, "", "me"):
            return self.me()
        return validation.account_id(str(value))

    def resolve_issue(self, ref: str) -> IssueRef:
        """Turn ``PROJ-123`` (or a numeric id) into an :class:`IssueRef`."""
        ref = ref.strip()
        if validation.is_issue_id(ref) and not self.has_jira:
            return IssueRef(id=int(ref))
        key = ref if validation.is_issue_id(ref) else validation.issue_key(ref)
        issue = self.jira(f"resolve the issue {key}").issue(key)
        fields = issue.get("fields") or {}
        return IssueRef(
            id=int(issue["id"]),
            key=issue.get("key"),
            project=(fields.get("project") or {}).get("key"),
            summary=fields.get("summary"),
        )

    def issue_map(self, worklogs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Best-effort id → issue lookup used to show keys next to worklogs."""
        if not self.has_jira or self.raw:
            return {}
        ids = [str((w.get("issue") or {}).get("id")) for w in worklogs]
        return self.jira("show issue keys").issues_by_ids(ids)

    # ------------------------------------------------------------------ writes

    def guard_write(
        self, *, action: str, request: dict[str, Any], yes: bool, dry_run: bool, summary: str
    ) -> bool:
        """Apply read-only mode, ``--dry-run`` and confirmation. True → perform the call."""
        self.policy.require_writable()
        if dry_run:
            self.printer.item({"dryRun": True, "action": action, "request": request})
            return False
        confirm(summary, yes=yes, action=action)
        return True


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def confirm(summary: str, *, yes: bool, action: str) -> None:
    if yes:
        return
    if _interactive():
        click.echo(summary, err=True)
        if not click.confirm("Proceed?", default=False, err=True):
            raise ConfirmationRequired("Cancelled by user", reason="cancelled")
        return
    raise ConfirmationRequired(
        f"{action} needs confirmation",
        hint="Review the action (use --dry-run to preview it), then re-run with --yes.",
        details={"action": action},
    )


def require_some(value: Any, message: str) -> Any:
    if value in (None, "", [], ()):
        raise ValidationError(message)
    return value
