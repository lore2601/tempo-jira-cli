# Setting up tempo

`tempo` talks to two APIs, always with **your own** permissions:

| API | Used for | Credential |
|---|---|---|
| Tempo REST API v4 | Worklogs, schedule, attributes, approvals | Tempo API token (Bearer) |
| Jira Cloud REST API v3 | Issue key ↔ id, issue summaries, your account id, JQL search | Atlassian email + API token |

Tempo v4 identifies issues only by numeric id and users only by Atlassian account id. The Jira API translates `PROJ-123` into that id.

## 1. Tempo API token

1. In Jira, open **Apps → Tempo → Settings** (gear icon in Tempo).
2. Go to **Data Access → API integration** and click **New token**.
3. Name it (e.g. `tempo-cli`), choose an expiry, and select the access you need. For full use, give read and write on worklogs, plus read on schedules, periods/approvals, work attributes and accounts.
4. Copy the token. It is shown only once.

The token can see and do only what your Tempo permissions allow. No admin rights are needed.

### Which region?

Tempo hosts data in different clusters. `https://api.tempo.io/4` (`--region global`, the default) works for most instances. If your instance lives in the EU or US cluster and you get `401 Unauthorized`, use `--region eu` (`https://api.eu.tempo.io/4`) or `--region us` (`https://api.us.tempo.io/4`).

## 2. Atlassian API token

1. Go to <https://id.atlassian.com/manage-profile/security/api-tokens>.
2. **Create API token**, name it `tempo-cli`, and copy it.
3. You also need your Jira site URL (e.g. `https://acme.atlassian.net`) and your Atlassian login email.

## 3. Log in

```bash
tempo auth login
```

You are prompted for the Jira URL, email and both tokens. Token input is hidden. Both tokens are checked against the APIs, and your account id and display name are stored with them in `~/.config/tempo-cli/credentials.json` with `0600` permissions.

```bash
tempo auth login --region eu                # regional Tempo cluster
tempo auth login --skip-jira                # Tempo only (numeric issue ids)
TEMPO_TOKEN_STORE=keyring tempo auth login  # store in the OS keyring (needs the [keyring] extra)
tempo auth status --check                   # verify later
tempo auth logout                           # delete stored credentials
```

### Environment variables (CI, containers, agents)

```bash
export TEMPO_API_TOKEN=...
export JIRA_URL=https://acme.atlassian.net
export JIRA_EMAIL=me@acme.com
export JIRA_API_TOKEN=...
export TEMPO_REGION=eu          # if needed
```

Environment variables override stored credentials field by field.

## 4. Optional: defaults and policy

```bash
tempo config init     # writes ~/.config/tempo-cli/config.toml
```

```toml
[defaults]
start_time = "09:00"          # used when --start is not given

[policy]
projects = ["PROJ", "OPS"]    # only allow logging on these projects
max_daily_hours = 10
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Tempo rejected the token` (401) | Wrong token, expired token, or wrong region: try `--region eu` / `--region us`. |
| `403 Forbidden` from Tempo | Your Tempo permissions do not allow it, e.g. the period is closed or the worklog belongs to someone else. |
| `Jira rejected the credentials` | Use your Atlassian **email** plus API token (not your password), and the `https://xxx.atlassian.net` URL. |
| `Work attribute … is required` | Run `tempo attributes list --required` and pass `-a KEY=VALUE`. |
| Issue not found | The key is wrong, or your Jira user cannot browse the project. |
