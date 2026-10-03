# tempo: Tempo Timesheets from the command line

[![CI](https://github.com/lore2601/tempo-jira-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/lore2601/tempo-jira-cli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/tempo-jira-cli?label=PyPI&cacheSeconds=3600)](https://pypi.org/project/tempo-jira-cli/)
[![CodeQL](https://github.com/lore2601/tempo-jira-cli/actions/workflows/codeql.yml/badge.svg)](https://github.com/lore2601/tempo-jira-cli/actions/workflows/codeql.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

`tempo` is a command-line interface for [Tempo Timesheets](https://www.tempo.io/) on **Jira Cloud**, built on the [Tempo REST API v4](https://apidocs.tempo.io/). It is meant for **AI agents** (Claude Code, Gemini CLI, Codex, scripts) and for people who want to log hours without leaving the terminal. You can log time on issues, review and fix worklogs, see which days are missing hours, and submit timesheets. Output is predictable JSON, and safety rails stop agents from logging nonsense.

> **Unofficial.** Not affiliated with or endorsed by Tempo Software or Atlassian.

```console
$ tempo log PROJ-123 1h30m -m "Code review" --yes
$ tempo log PROJ-87 2h -d yesterday -s 14:00 -m "Pairing on the importer" --yes

$ tempo summary
DATE        DAY  TYPE         REQUIRED  LOGGED  MISSING
2026-09-28  Mon  WORKING_DAY  8h        8h
2026-09-29  Tue  WORKING_DAY  8h        6h 30m  1h 30m
2026-09-30  Wed  WORKING_DAY  8h        8h
...

$ tempo worklogs list -p yesterday -f json
{"worklogs":[{"id":4021,"issue":"PROJ-87","issueId":10087,"summary":"CSV importer","date":"2026-10-02","start":"14:00:00","duration":"2h","seconds":7200,"description":"Pairing on the importer","author":"5b10…"}],"from":"2026-10-02","to":"2026-10-02","count":1,"totalSeconds":7200,"total":"2h","totalHours":2.0}
```

## Features

- **Log time naturally.** Durations like `1h30m`, `1.5h`, `90m` or `1:30`. Dates like `today`, `yesterday`, `-2d`, `monday` or `2026-10-01`. Issues by **Jira key**: the CLI resolves keys to the numeric ids Tempo v4 requires.
- **Batch logging** from JSON or CSV (`tempo log-batch week.json`). Every entry is validated before anything is written.
- **Gap detection.** `tempo summary` compares your worklogs with your Tempo work schedule, holidays included, and lists the days with missing hours.
- **Fix mistakes.** `tempo worklogs update` changes only the fields you pass. Attributes, description and start time are preserved, and billable time follows the duration.
- **Find issues.** Open issues assigned to you, issues you logged on recently, full-text search or JQL.
- **Work attributes, accounts, approval periods, timesheet submission**, plus an `api` escape hatch for any Tempo or Jira endpoint.
- **Agent-friendly:**
  - JSON when piped
  - compact views
  - `--fields`
  - stable exit codes
  - JSON errors with hints
  - `tempo schema` introspection
  - a ready-made [agent skill](skills/tempo/SKILL.md) and a Claude Code plugin

## Install

Requires Python 3.11+.

```bash
pipx install tempo-jira-cli          # or: uv tool install tempo-jira-cli
# development version:
pipx install git+https://github.com/lore2601/tempo-jira-cli
```

Optional: keep tokens in the OS keyring with `pipx install "tempo-jira-cli[keyring]"` and `export TEMPO_TOKEN_STORE=keyring`.

## Set up (2 minutes)

You need two tokens. Neither needs admin rights, and both act with **your own** permissions. Details are in [docs/setup.md](docs/setup.md).

1. **Tempo API token:** in Jira, open *Tempo → Settings → API integration → New token*. Give it access to worklogs and schedules.
2. **Atlassian API token:** create one at <https://id.atlassian.com/manage-profile/security/api-tokens>. It is used to resolve issue keys and your account id.

```bash
tempo auth login            # prompts for Jira URL, email and both tokens (hidden input)
tempo auth status --check
```

If your Tempo data lives in a regional cluster, add `--region eu` or `--region us`. Agents and CI can use environment variables instead: `TEMPO_API_TOKEN`, `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.

## Commands

| Command | What it does |
|---|---|
| `tempo log ISSUE DURATION [-d DATE] [-s HH:MM] [-m TEXT] [-a KEY=VALUE]…` | Log time on an issue |
| `tempo log-batch FILE\|-` | Log many worklogs from JSON/CSV |
| `tempo worklogs list [-p week\|last-week\|month…] [--from/--to] [-i ISSUE] [--project KEY] [-u me\|ID\|all]` | List worklogs with totals |
| `tempo worklogs get\|update\|delete ID` | Inspect, change or delete a worklog |
| `tempo summary [-p …] [--by day\|issue]` | Logged vs required per day, or totals per issue |
| `tempo issues list [--preset assigned\|recent\|watching] [-q TEXT] [--jql …]` / `issues get KEY` | Find issues to log on |
| `tempo attributes list [--required]` | Work attributes and allowed values |
| `tempo accounts list` | Tempo accounts |
| `tempo approvals periods\|status\|reviewers\|submit` | Timesheet approvals |
| `tempo api METHOD PATH [--jira] [-p JSON] [-b JSON]` | Any Tempo (or Jira) REST endpoint |
| `tempo auth login\|status\|logout` | Credentials |
| `tempo config show\|init` | Effective policy and file locations |
| `tempo schema [COMMAND]` | Every command, option and exit code as JSON |

Periods: `today`, `yesterday`, `week`, `last-week`, `month`, `last-month`. Weeks start on Monday. Run `tempo COMMAND --help` for every option.

### Batch file format

```json
[
  {"issue": "PROJ-1", "duration": "4h", "date": "monday", "start": "09:00", "description": "Sprint planning"},
  {"issue": "PROJ-7", "duration": "3h30m", "date": "monday", "attributes": {"_Role_": "Developer"}}
]
```

CSV works too: `issue,duration,date,start,description,attributes`, with attributes written as `K=V;K2=V2`.

## Output and exit codes

- stdout carries only data. On a terminal you get tables; when piped you get JSON. Force a format with `-f json|ndjson|table` or `TEMPO_FORMAT`.
- `--fields id,issue,duration` trims output. `--raw` returns untouched Tempo objects.
- Errors are a single JSON object on stderr, for example `{"error": {"exitCode": 4, "reason": "duplicateWorklog", "message": "…", "hint": "…"}}`.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Tempo/Jira API or network error (incl. partial batch failure) |
| 2 | Authentication problem |
| 3 | Invalid input (bad key, duration, date, …) |
| 4 | Blocked by local policy, duplicate, or confirmation (`--yes`) missing |
| 5 | Internal error (please report it) |

## Safety rails

Timesheets feed payroll, invoicing and approvals, so mistakes are expensive. Before anything is written, `tempo` checks:

| Check | Default | Override |
|---|---|---|
| Writes need `--yes` when not on a TTY (agents, scripts); `--dry-run` previews | on | none |
| Identical worklog already exists (same issue, day, duration, description) | refuse | `--allow-duplicate` |
| A single worklog longer than N hours | 12h | `max_worklog_hours` / `TEMPO_MAX_WORKLOG_HOURS` |
| Day total above N hours, existing worklogs included | 14h | `max_daily_hours` / `TEMPO_MAX_DAILY_HOURS` |
| Worklogs dated in the future | refuse | `allow_future_dates` / `TEMPO_ALLOW_FUTURE_DATES` |
| Logging for another user (`--author`) | refuse | `allow_other_authors` / `TEMPO_ALLOW_OTHER_AUTHORS` |
| Project allowlist | any | `projects = ["PROJ"]` / `TEMPO_ALLOW_PROJECTS` |
| Read-only mode | off | `read_only` / `TEMPO_READ_ONLY=1` |

Configure them in `~/.config/tempo-cli/config.toml` (`tempo config init` writes a commented template). Tokens are stored with `0600` permissions or in the OS keyring, and no command ever prints them. All arguments (issue keys, ids, dates, attribute keys) are validated before they reach a URL.

## Using it with AI agents

- **Claude Code plugin:** `/plugin marketplace add lore2601/tempo-jira-cli`, then `/plugin install tempo@tempo-jira-cli`.
- **Any agent:** copy [`skills/tempo/SKILL.md`](skills/tempo/SKILL.md) into its instructions, or let it run `tempo schema`.
- Typical prompt: *"Log today's work: 2h on PROJ-12 (code review), the rest on PROJ-40, then show me what's missing this week."* The agent runs `tempo issues list --preset recent`, previews with `--dry-run`, asks you, then logs with `--yes`.

See [docs/agents.md](docs/agents.md) for permission rules and recipes.

## Configuration reference

| Variable | Purpose |
|---|---|
| `TEMPO_API_TOKEN` | Tempo token |
| `TEMPO_REGION` / `TEMPO_BASE_URL` | `eu`, `us`, `global` (default) / explicit base URL |
| `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | Jira Cloud site and Atlassian API token |
| `TEMPO_ACCOUNT_ID` | Your Atlassian account id (skips the Jira lookup) |
| `TEMPO_CONFIG_DIR` / `TEMPO_CONFIG` / `TEMPO_CREDENTIALS_FILE` | File locations (default `~/.config/tempo-cli/`) |
| `TEMPO_TOKEN_STORE` | `file` (default) or `keyring` |
| `TEMPO_FORMAT` | Default output format |
| `TEMPO_READ_ONLY`, `TEMPO_ALLOW_PROJECTS`, `TEMPO_MAX_WORKLOG_HOURS`, `TEMPO_MAX_DAILY_HOURS`, `TEMPO_ALLOW_FUTURE_DATES`, `TEMPO_ALLOW_OTHER_AUTHORS` | Policy overrides |

## Limitations

- Jira **Cloud** with Tempo Cloud only. Jira Data Center uses a different Tempo API.
- Without Jira credentials you can still use numeric issue ids (`tempo log 10001 1h`), but not keys, summaries or the project allowlist.
- `summary` uses the schedule of the token's owner, so it only covers your own timesheet.

## Contributing

Issues and PRs are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately ([SECURITY.md](SECURITY.md)).

## License

[Apache-2.0](LICENSE)
