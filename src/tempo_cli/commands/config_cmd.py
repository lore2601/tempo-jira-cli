"""``tempo config``: inspect and initialise the configuration."""

from __future__ import annotations

import os

import click

from tempo_cli import config
from tempo_cli.commands._common import pass_app
from tempo_cli.context import AppContext
from tempo_cli.errors import ValidationError


@click.group("config")
def group() -> None:
    """Configuration file and local safety policy."""


@group.command("show")
@pass_app
def show(app: AppContext) -> None:
    """Show the effective policy, defaults and file locations."""
    app.printer.item(
        {
            "configFile": str(config.config_file(app.env)),
            "configLoaded": app.config.source is not None,
            "credentialsFile": str(config.credentials_file(app.env)),
            "policy": app.policy.as_dict(),
            "defaults": app.config.defaults,
        }
    )


@group.command("init")
@click.option("--force", is_flag=True, help="Overwrite an existing config file.")
@pass_app
def init(app: AppContext, force: bool) -> None:
    """Write a commented sample config file."""
    path = config.config_file(app.env)
    if path.exists() and not force:
        raise ValidationError(f"{path} already exists", hint="Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(config.SAMPLE_CONFIG, encoding="utf-8")
    os.chmod(path, 0o600)
    app.printer.item({"created": str(path)})
