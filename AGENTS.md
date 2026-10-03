# Notes for coding agents working on this repository

- Python 3.11+, package in `src/tempo_cli`, CLI built with `click`, HTTP with `requests`.
- Layout:
  - `clients.py`: `TempoClient` (v4, Bearer, offset/limit pagination) and `JiraClient`
    (v3, basic auth, key↔id resolution, JQL), with retries.
  - `credentials.py`: token resolution (environment over store), regions, `0600` file or
    keyring.
  - `config.py`: paths and `Policy`.
  - `validation.py`: durations, dates, periods, keys, ids, attributes.
  - `worklog_plan.py`: building worklog bodies and every create-time safety check.
  - `views.py` (compact output), `output.py` (formats), `context.py` (`AppContext`,
    `resolve_issue`, `guard_write`).
  - `commands/*`: one click group or command per module.
  - `cli.py`: root command and error handling.
- Run `uv run ruff format src tests && uv run ruff check src tests && uv run mypy && uv run pytest`
  before finishing. Coverage must stay at or above 80%.
- Every write must call `app.guard_write(...)`. New worklog-creating paths must go through
  `worklog_plan.plan` and `check_against_existing`. Validate every argument in
  `validation.py`, and add tests for rejected input.
- Never add network calls to unit tests. Mock them with `responses` (see `tests/conftest.py`).
- Keep `skills/tempo/SKILL.md` and `README.md` in sync with the command surface.
