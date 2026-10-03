# Using tempo with AI agents

Logging hours is a good job for a coding agent. It already knows which issue it worked on, and it can turn a short list like "2h review on PROJ-12, rest on PROJ-40" into correct worklogs. `tempo` gives it a safe, predictable interface for this.

## Contract

| Feature | Detail |
|---|---|
| Output | JSON when stdout is not a TTY; `-f ndjson` for streams |
| Lists | `{"worklogs": [...], "count": n, "totalSeconds": s, "total": "7h 30m", "from": …, "to": …}` |
| Errors | One JSON object on stderr: `exitCode`, `reason`, `message`, `hint` (+ `service`, `httpStatus`) |
| Exit codes | `0` ok · `1` API/network/partial batch · `2` auth · `3` invalid input · `4` policy/duplicate/confirmation · `5` bug |
| Introspection | `tempo schema`, `tempo schema "worklogs update"` |
| Preview | `--dry-run` on every write prints the exact request |

## Recommended workflow for agents

1. `tempo auth status`. If it is not configured, ask the user to run `tempo auth login`.
2. Find the issue: `tempo issues list --preset recent` or `--preset assigned`, or `-q "text"`.
3. Check required attributes once: `tempo attributes list --required`.
4. Preview: `tempo log PROJ-12 2h -d today -m "Code review" --dry-run`.
5. Show the user the summary, get approval, then run the same command with `--yes`.
6. Verify: `tempo summary` or `tempo worklogs list -p today`.

## Guard rails

- Without `--yes`, every write fails with exit code `4` (`confirmationRequired`), so the agent's intent is always explicit.
- Duplicate protection: re-running the same `tempo log` returns `duplicateWorklog` (exit `4`) and the id of the existing worklog. Agents that retry after a timeout therefore do not double-log.
- Daily limit, single-worklog limit, future-date and other-author protection are described in the README.
- For an unattended agent, also restrict projects: `TEMPO_ALLOW_PROJECTS=PROJ,OPS`.
- For a reporting-only agent, set `TEMPO_READ_ONLY=1`.

## Claude Code permissions

`.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(tempo worklogs list:*)",
      "Bash(tempo worklogs get:*)",
      "Bash(tempo summary:*)",
      "Bash(tempo issues:*)",
      "Bash(tempo attributes list:*)",
      "Bash(tempo approvals status:*)",
      "Bash(tempo schema:*)",
      "Bash(tempo auth status:*)"
    ],
    "ask": [
      "Bash(tempo log:*)",
      "Bash(tempo log-batch:*)",
      "Bash(tempo worklogs update:*)",
      "Bash(tempo worklogs delete:*)",
      "Bash(tempo approvals submit:*)",
      "Bash(tempo api:*)"
    ]
  }
}
```

## Installing the skill

- **Claude Code plugin:**
  ```
  /plugin marketplace add lore2601/tempo-jira-cli
  /plugin install tempo@tempo-jira-cli
  ```
- **Manual:** copy `skills/tempo/` to `~/.claude/skills/tempo/`. For other agents, add the content of `skills/tempo/SKILL.md` to `AGENTS.md` / `GEMINI.md`.

## Recipes

```bash
# End of day: what did I log today, and what's missing this week?
tempo worklogs list -p today --fields issue,duration,description
tempo summary --fields date,missing

# Fill a whole week from a plan the agent prepared
tempo log-batch week.json --dry-run && tempo log-batch week.json --yes

# Fix a wrong duration
tempo worklogs update 4021 --duration 1h30m --yes

# Hours per issue last month (for a status report)
tempo summary -p last-month --by issue -f json

# Submit the timesheet for approval
tempo approvals status && tempo approvals submit --yes
```
