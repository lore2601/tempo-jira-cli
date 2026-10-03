"""``tempo schema``: machine-readable description of every command.

Agents can call this once to learn the full command surface (arguments,
options, types, defaults) without scraping ``--help`` output.
"""

from __future__ import annotations

from typing import Any

import click

from tempo_cli import __version__
from tempo_cli.commands._common import pass_app
from tempo_cli.context import AppContext
from tempo_cli.errors import ExitCode, ValidationError


def _param(param: click.Parameter) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": param.name,
        "kind": "argument" if isinstance(param, click.Argument) else "option",
        "type": param.type.name,
        "required": param.required,
    }
    if isinstance(param, click.Option):
        info["flags"] = list(param.opts) + list(param.secondary_opts)
        info["help"] = param.help
        info["isFlag"] = param.is_flag
        info["multiple"] = param.multiple
        if isinstance(param.default, str | int | float | bool) and not param.is_flag:
            info["default"] = param.default
    elif param.nargs != 1:
        info["nargs"] = param.nargs
    if isinstance(param.type, click.Choice):
        info["choices"] = list(param.type.choices)
    return {k: v for k, v in info.items() if v not in (None, False) or k == "required"}


def describe(cmd: click.Command, path: list[str]) -> list[dict[str, Any]]:
    if isinstance(cmd, click.Group):
        result: list[dict[str, Any]] = []
        for name in sorted(cmd.commands):
            result.extend(describe(cmd.commands[name], [*path, name]))
        return result
    params = [p for p in cmd.params if p.name not in {"help"}]
    return [
        {
            "command": " ".join(path),
            "summary": cmd.get_short_help_str(limit=200),
            "help": (cmd.help or "").replace("\b\n", "").strip(),
            "params": [_param(p) for p in params],
        }
    ]


@click.command("schema")
@click.argument("command", required=False)
@pass_app
@click.pass_context
def group(ctx: click.Context, app: AppContext, command: str | None) -> None:
    """Describe every command as JSON, for agents and tooling.

    Pass COMMAND (e.g. "worklogs list") to describe a single command.
    """
    root = ctx.find_root().command
    commands = describe(root, ["tempo"])
    if command:
        wanted = "tempo " + command.strip()
        commands = [c for c in commands if c["command"] == wanted]
        if not commands:
            raise ValidationError(f"Unknown command: {command!r}")
        app.printer.item(commands[0])
        return
    global_params = [_param(p) for p in root.params if p.name not in {"help", "version"}]
    app.printer.item(
        {
            "name": "tempo",
            "version": __version__,
            "globalOptions": global_params,
            "exitCodes": {code.name.lower(): int(code) for code in ExitCode},
            "commands": commands,
        }
    )
