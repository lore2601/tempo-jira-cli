# Security policy

## Supported versions

Only the latest released version receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through
[GitHub Security Advisories](https://github.com/lore2601/tempo-jira-cli/security/advisories/new).
Include steps to reproduce and the impact. You should get an answer within 7 days.

## Scope and threat model

`tempo` acts with the Tempo and Atlassian API tokens of the person who configured it.
The main risks are:

- **Credential exposure.** Tokens are stored in `~/.config/tempo-cli/credentials.json`
  (mode `0600`) or in the OS keyring, and must never be printed or logged.
- **Wrong or manipulated timesheet entries.** An agent might log, change or delete hours
  incorrectly, or be steered by text in issue summaries. Mitigations are mandatory
  `--yes`, `--dry-run`, duplicate detection, hour limits, future-date and other-author
  protection, the project allowlist and read-only mode. Bypasses of these controls are
  in scope.
- **Injection** through arguments (issue keys, ids, JQL fragments) into request URLs.

Out of scope: issues in the Tempo or Jira APIs themselves, and a compromised local user
account.
