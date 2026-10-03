"""``tempo auth``: store, check and remove Tempo/Jira credentials."""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

import click

from tempo_cli import credentials
from tempo_cli.clients import JiraClient, TempoClient
from tempo_cli.commands._common import pass_app
from tempo_cli.context import AppContext
from tempo_cli.credentials import REGIONS, CredentialStore
from tempo_cli.errors import ApiError, AuthError


@click.group("auth")
def group() -> None:
    """Manage Tempo and Jira credentials."""


def _secret(env_value: str | None, prompt: str, interactive: bool) -> str | None:
    if env_value:
        return env_value
    if not interactive:
        return None
    value = click.prompt(prompt, hide_input=True, default="", show_default=False, err=True)
    return str(value).strip() or None


def _check_tempo(app: AppContext, token: str, base_url: str) -> None:
    today = date.today().isoformat()
    client = (
        app.tempo_factory(credentials.Credentials(tempo_token=token, base_url=base_url))
        if app.tempo_factory
        else TempoClient(token, base_url, max_retries=1)
    )
    try:
        client.request("GET", "user-schedule", params={"from": today, "to": today})
    except ApiError as exc:
        if exc.http_status in (401, 403):
            raise AuthError(
                f"Tempo rejected the token for {base_url}",
                hint="Check the token, and try --region eu or --region us if your Tempo data "
                "lives in a regional cluster.",
            ) from exc
        raise


def _check_jira(app: AppContext, url: str, email: str, token: str) -> dict[str, Any]:
    creds = credentials.Credentials(jira_url=url, jira_email=email, jira_token=token)
    client = (
        app.jira_factory(creds)
        if app.jira_factory
        else JiraClient(url, email, token, max_retries=1)
    )
    try:
        return client.myself()
    except ApiError as exc:
        if exc.http_status in (401, 403, 404):
            raise AuthError(
                f"Jira rejected the credentials for {url}",
                hint="Use your Atlassian account email and an API token from "
                "https://id.atlassian.com/manage-profile/security/api-tokens",
            ) from exc
        raise


@group.command("login")
@click.option(
    "--region",
    type=click.Choice(list(REGIONS)),
    default=None,
    help="Tempo cluster: eu, us or global (default: global, or TEMPO_REGION).",
)
@click.option("--jira-url", default=None, help="Jira site, e.g. https://acme.atlassian.net")
@click.option("--jira-email", default=None, help="Your Atlassian account email.")
@click.option("--skip-jira", is_flag=True, help="Only store the Tempo token.")
@click.option("--no-verify", is_flag=True, help="Store credentials without testing them.")
@pass_app
def login(
    app: AppContext,
    region: str | None,
    jira_url: str | None,
    jira_email: str | None,
    skip_jira: bool,
    no_verify: bool,
) -> None:
    """Store your Tempo token and Jira API token (prompted, never echoed).

    \b
    Tokens are read from TEMPO_API_TOKEN / JIRA_API_TOKEN when set, otherwise
    prompted for. Get them from:
      Tempo: Tempo → Settings → API integration → New token
      Jira:  https://id.atlassian.com/manage-profile/security/api-tokens
    """
    env = app.env
    interactive = sys.stdin.isatty()
    store = CredentialStore(env)
    stored = store.load()

    region = (region or env.get("TEMPO_REGION") or stored.get("region") or "global").lower()
    base_url = env.get("TEMPO_BASE_URL") or credentials.base_url_for(region)
    tempo_token = _secret(env.get("TEMPO_API_TOKEN"), "Tempo API token", interactive)
    tempo_token = tempo_token or stored.get("tempo_token")
    if not tempo_token:
        raise AuthError(
            "No Tempo token provided",
            hint="Run in a terminal to be prompted, or set TEMPO_API_TOKEN.",
        )

    data: dict[str, Any] = {**stored, "tempo_token": tempo_token, "region": region}
    if env.get("TEMPO_BASE_URL"):
        data["base_url"] = base_url

    if not no_verify:
        _check_tempo(app, tempo_token, base_url)

    result: dict[str, Any] = {
        "tempo": {"region": region, "baseUrl": base_url, "verified": not no_verify}
    }

    if not skip_jira:
        url = jira_url or env.get("JIRA_URL") or stored.get("jira_url")
        if not url and interactive:
            url = click.prompt("Jira site URL (https://xxx.atlassian.net)", err=True)
        email = jira_email or env.get("JIRA_EMAIL") or stored.get("jira_email")
        if not email and interactive:
            email = click.prompt("Atlassian account email", err=True)
        token = _secret(env.get("JIRA_API_TOKEN"), "Jira API token", interactive)
        token = token or stored.get("jira_token")
        if not (url and email and token):
            raise AuthError(
                "Jira URL, email and API token are required",
                hint="Pass --skip-jira to store only the Tempo token (issue keys will not "
                "work), or set JIRA_URL, JIRA_EMAIL and JIRA_API_TOKEN.",
            )
        url = credentials.normalise_jira_url(url)
        data.update({"jira_url": url, "jira_email": email.strip(), "jira_token": token})
        jira_info: dict[str, Any] = {"url": url, "email": email.strip(), "verified": False}
        if not no_verify:
            me = _check_jira(app, url, email.strip(), token)
            data["account_id"] = me.get("accountId")
            data["display_name"] = me.get("displayName")
            data["time_zone"] = me.get("timeZone")
            jira_info.update(
                {
                    "verified": True,
                    "accountId": me.get("accountId"),
                    "displayName": me.get("displayName"),
                }
            )
        result["jira"] = jira_info

    store.save({k: v for k, v in data.items() if v is not None})
    result["store"] = store.location
    app.printer.item(result)


@group.command("status")
@click.option("--check", is_flag=True, help="Also call Tempo and Jira to verify the credentials.")
@pass_app
def status(app: AppContext, check: bool) -> None:
    """Show the configured credentials (never prints secrets)."""
    creds = app.creds
    result: dict[str, Any] = {
        "tempo": {
            "configured": bool(creds.tempo_token),
            "source": creds.sources.get("tempo_token"),
            "region": creds.region,
            "baseUrl": creds.tempo_base_url,
        },
        "jira": {
            "configured": creds.has_jira,
            "url": creds.jira_url,
            "email": creds.jira_email,
            "tokenSource": creds.sources.get("jira_token"),
        },
        "accountId": creds.account_id,
        "displayName": creds.display_name,
        "store": CredentialStore(app.env).location,
    }
    if check:
        if creds.tempo_token:
            _check_tempo(app, creds.tempo_token, creds.tempo_base_url)
            result["tempo"]["verified"] = True
        if creds.has_jira:
            me = _check_jira(app, str(creds.jira_url), str(creds.jira_email), str(creds.jira_token))
            result["jira"]["verified"] = True
            result["accountId"] = me.get("accountId")
    if not creds.tempo_token:
        result["hint"] = "Run `tempo auth login`."
    app.printer.item(result)


@group.command("logout")
@pass_app
def logout(app: AppContext) -> None:
    """Delete stored credentials (tokens stay valid until you revoke them in Tempo/Atlassian)."""
    store = CredentialStore(app.env)
    app.printer.item({"loggedOut": True, "removed": store.delete(), "store": store.location})
