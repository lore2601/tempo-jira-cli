# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-03

### Added

- `tempo log` with natural durations (`1h30m`, `1.5h`, `1:30`), dates (`yesterday`, `-2d`,
  `monday`), start time, description, billable/remaining time and work attributes. Jira
  issue keys are resolved to Tempo issue ids automatically.
- `tempo log-batch` for JSON/CSV files or stdin, validated as a whole before writing.
- `tempo worklogs list | get | update | delete`, with totals, issue keys and summaries.
  `update` preserves unspecified fields and keeps billable time in step with the duration.
- `tempo summary`: required vs logged vs missing per day (from the Tempo user schedule,
  holidays included), or totals per issue.
- `tempo issues list | get` (assigned / recently logged / watching presets, text search,
  JQL), `attributes list`, `accounts list`, `approvals periods | status | reviewers | submit`.
- `tempo api` escape hatch for Tempo and Jira, `tempo schema`, `tempo config show | init`.
- `tempo auth login | status | logout` with verification, EU/US/global regions, `0600`
  credentials file or OS keyring, and environment-variable overrides.
- Safety rails: mandatory `--yes` for non-interactive writes, `--dry-run`, duplicate
  detection, daily and per-worklog hour limits, future-date and other-author protection,
  project allowlist, read-only mode.
- JSON / NDJSON / table output, `--fields`, `--raw`, stable exit codes, JSON errors with
  hints, retries with backoff.
- Agent skill (`skills/tempo/SKILL.md`) and Claude Code plugin marketplace manifest.

[Unreleased]: https://github.com/lore2601/tempo-jira-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lore2601/tempo-jira-cli/releases/tag/v0.1.0
