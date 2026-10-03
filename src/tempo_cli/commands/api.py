"""``tempo api``: call any Tempo (or Jira) REST endpoint directly."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import click

from tempo_cli.commands._common import pass_app, write_options
from tempo_cli.context import AppContext
from tempo_cli.errors import ValidationError

_PATH_RE = re.compile(r"^[A-Za-z0-9_.@:~/-]+$")


def _parse_json(value: str | None, what: str) -> Any:
    if value is None:
        return None
    if value == "-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        try:
            with open(value[1:], encoding="utf-8") as handle:
                value = handle.read()
        except OSError as exc:
            raise ValidationError(f"Cannot read {what} file: {exc}") from exc
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{what} is not valid JSON: {exc}") from exc


def _pretty(payload: Any) -> str:
    return json.dumps(payload, indent=2) if payload else ""


def _validate_path(path: str) -> str:
    path = path.strip().lstrip("/")
    for prefix in ("4/", "rest/api/3/"):
        path = path.removeprefix(prefix)
    if not path or not _PATH_RE.match(path) or ".." in path.split("/"):
        raise ValidationError(
            f"Invalid API path: {path!r}",
            hint="Pass a path such as worklogs/123 (query parameters go in --params).",
        )
    return path


@click.command("api")
@click.argument(
    "method", type=click.Choice(["GET", "POST", "PUT", "PATCH", "DELETE"], case_sensitive=False)
)
@click.argument("path")
@click.option("--jira", "use_jira", is_flag=True, help="Call the Jira REST API v3 instead.")
@click.option("-p", "--params", default=None, help="Query parameters as a JSON object.")
@click.option("-b", "--body", default=None, help="Request body as JSON, @file or '-' for stdin.")
@write_options
@pass_app
def group(
    app: AppContext,
    method: str,
    path: str,
    use_jira: bool,
    params: str | None,
    body: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Call any Tempo REST endpoint (escape hatch). Output is the raw response.

    \b
    Examples:
      tempo api GET worklogs/user/<accountId> -p '{"from":"2026-01-01","to":"2026-01-31"}'
      tempo api GET myself --jira

    PATH is relative to the Tempo base URL (https://api.tempo.io/4/) or, with
    --jira, to https://<site>/rest/api/3/. GET is read-only and runs immediately;
    POST/PUT/PATCH/DELETE are writes, so --yes is required (or the TTY prompt) and
    --dry-run works.
    """
    method = method.upper()
    path = _validate_path(path)
    query = _parse_json(params, "--params")
    if query is not None and not isinstance(query, dict):
        raise ValidationError("--params must be a JSON object")
    payload = _parse_json(body, "--body")
    service = "jira" if use_jira else "tempo"
    request = {"service": service, "method": method, "path": path, "params": query, "body": payload}
    if method != "GET":
        if not app.guard_write(
            action=f"api.{method.lower()}",
            request=request,
            yes=yes,
            dry_run=dry_run,
            summary=f"{method} {service}:/{path}\n{_pretty(payload)}",
        ):
            return
    elif dry_run:
        app.printer.item({"dryRun": True, "request": request})
        return
    client = app.jira("call the Jira API") if use_jira else app.tempo
    result = client.request(method, path, params=query, body=payload)
    app.printer.item(result if isinstance(result, dict) else {"result": result})
