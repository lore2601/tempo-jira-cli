from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import responses
from responses import matchers

from tempo_cli import __version__
from tests.conftest import JIRA, ME, TEMPO, Result, issue_json, page, worklog_json

Invoke = Callable[..., Result]


def mock_issue(api: responses.RequestsMock, key: str = "PROJ-1", issue_id: int = 10001) -> None:
    api.get(f"{JIRA}/issue/{key}", json=issue_json(key, issue_id))


def mock_existing(
    api: responses.RequestsMock, worklogs: list[dict[str, Any]] | None = None
) -> None:
    api.post(f"{TEMPO}/worklogs/search", json=page(worklogs or []))


def bodies(api: responses.RequestsMock, method: str, path: str) -> list[Any]:
    return [
        json.loads(c.request.body)
        for c in api.calls
        if c.request.method == method and c.request.url.split("?")[0].endswith(path)
    ]


# --------------------------------------------------------------------------- basics


def test_version_and_help(tempo_cli: Invoke) -> None:
    assert __version__ in tempo_cli("--version").out
    assert tempo_cli().code == 0


def test_usage_error(tempo_cli: Invoke) -> None:
    result = tempo_cli("log", "PROJ-1")
    assert result.code == 3
    assert result.error["reason"] == "invalidArgument"


def test_missing_credentials(tempo_cli: Invoke) -> None:
    result = tempo_cli("worklogs", "list", "-p", "week")
    assert result.code == 2
    assert "Jira" in result.error["message"] or "Tempo" in result.error["message"]


def test_missing_tempo_token(tempo_cli: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPO_ACCOUNT_ID", ME)
    result = tempo_cli("worklogs", "list")
    assert result.code == 2
    assert "Tempo API token" in result.error["message"]


# --------------------------------------------------------------------------- log


def test_log_creates_worklog(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    mock_existing(api)
    api.post(f"{TEMPO}/worklogs", json=worklog_json(99, seconds=5400, description="Review"))
    result = tempo_cli(
        "log",
        "proj-1",
        "1h30m",
        "-d",
        "2026-01-05",
        "-s",
        "9:00",
        "-m",
        "Review",
        "-a",
        "_Role_=Dev",
        "--billable",
        "1h",
        "--yes",
    )
    assert result.code == 0, result.err
    assert result.json["id"] == 99
    assert result.json["issue"] == "PROJ-1"
    assert result.json["duration"] == "1h 30m"
    body = bodies(api, "POST", "/worklogs")[0]
    assert body == {
        "authorAccountId": ME,
        "startDate": "2026-01-05",
        "timeSpentSeconds": 5400,
        "startTime": "09:00:00",
        "description": "Review",
        "billableSeconds": 3600,
        "attributes": [{"key": "_Role_", "value": "Dev"}],
        "issueId": 10001,
    }


def test_log_requires_yes_without_tty(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    mock_existing(api)
    result = tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05")
    assert result.code == 4
    assert result.error["reason"] == "confirmationRequired"
    assert not bodies(api, "POST", "/worklogs")


def test_log_dry_run(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    mock_existing(api)
    result = tempo_cli("log", "PROJ-1", "2h", "-d", "2026-01-05", "--dry-run")
    assert result.code == 0
    assert result.json["dryRun"] is True
    assert result.json["request"]["body"]["timeSpentSeconds"] == 7200
    assert not bodies(api, "POST", "/worklogs")


def test_log_uses_default_start_time(
    tempo_cli: Invoke, api: responses.RequestsMock, tmp_path: Path
) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "config.toml").write_text('[defaults]\nstart_time = "08:30"\n')
    mock_issue(api)
    mock_existing(api)
    result = tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05", "--dry-run")
    assert result.json["request"]["body"]["startTime"] == "08:30:00"


def test_log_refuses_duplicate(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    mock_existing(api, [worklog_json(7, seconds=3600, description="Work")])
    result = tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05", "-m", "Work", "--yes")
    assert result.code == 4
    assert result.error["reason"] == "duplicateWorklog"
    assert result.error["existingWorklogId"] == 7
    api.post(f"{TEMPO}/worklogs", json=worklog_json(8))
    result = tempo_cli(
        "log", "PROJ-1", "1h", "-d", "2026-01-05", "-m", "Work", "--allow-duplicate", "--yes"
    )
    assert result.code == 0


def test_log_daily_limit(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    mock_existing(api, [worklog_json(1, seconds=13 * 3600, description="Long day")])
    result = tempo_cli("log", "PROJ-1", "2h", "-d", "2026-01-05", "--yes")
    assert result.code == 4
    assert "daily limit" in result.error["message"]


def test_log_single_worklog_limit(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    result = tempo_cli("log", "PROJ-1", "13h", "-d", "2026-01-05", "--yes")
    assert result.code == 4
    assert "exceeds" in result.error["message"]


def test_log_future_date_blocked(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    result = tempo_cli("log", "PROJ-1", "1h", "-d", tomorrow, "--yes")
    assert result.code == 4
    assert "future" in result.error["message"]
    monkeypatch.setenv("TEMPO_ALLOW_FUTURE_DATES", "1")
    mock_issue(api)
    mock_existing(api)
    assert tempo_cli("log", "PROJ-1", "1h", "-d", tomorrow, "--dry-run").code == 0


def test_log_project_allowlist(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPO_ALLOW_PROJECTS", "OTHER")
    mock_issue(api)
    result = tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05", "--yes")
    assert result.code == 4
    assert "PROJ" in result.error["message"]


def test_log_other_author_blocked(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05", "--author", "someone-else-1")
    assert result.code == 4
    monkeypatch.setenv("TEMPO_ALLOW_OTHER_AUTHORS", "true")
    mock_issue(api)
    mock_existing(api)
    result = tempo_cli(
        "log", "PROJ-1", "1h", "-d", "2026-01-05", "--author", "someone-else-1", "--dry-run"
    )
    assert result.json["request"]["body"]["authorAccountId"] == "someone-else-1"


def test_log_read_only(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPO_READ_ONLY", "1")
    assert tempo_cli("log", "PROJ-1", "1h", "--yes").code == 4


def test_log_numeric_issue_without_jira(tempo_cli: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPO_API_TOKEN", "t")
    monkeypatch.setenv("TEMPO_ACCOUNT_ID", ME)
    with responses.RequestsMock() as api:
        mock_existing(api)
        result = tempo_cli("log", "10001", "1h", "-d", "2026-01-05", "--dry-run")
    assert result.code == 0, result.err
    assert result.json["request"]["body"]["issueId"] == 10001
    monkeypatch.setenv("TEMPO_ALLOW_PROJECTS", "PROJ")
    assert tempo_cli("log", "10001", "1h", "-d", "2026-01-05", "--dry-run").code == 4
    assert tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05", "--dry-run").code == 2


@pytest.mark.parametrize(
    "args",
    [
        ("log", "PROJ-1", "abc"),
        ("log", "NOT A KEY", "1h", "-d", "2026-01-05"),
        ("log", "PROJ-1", "1h", "-d", "someday"),
        ("log", "PROJ-1", "1h", "-d", "2026-01-05", "-s", "25:00"),
        ("log", "PROJ-1", "1h", "-d", "2026-01-05", "-a", "novalue"),
    ],
)
def test_log_invalid_input(
    tempo_cli: Invoke, api: responses.RequestsMock, args: tuple[str, ...]
) -> None:
    mock_issue(api)
    assert tempo_cli(*args).code == 3


def test_log_api_error(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    mock_existing(api)
    api.post(
        f"{TEMPO}/worklogs",
        status=400,
        json={"errors": [{"message": "Work attribute _Role_ is required"}]},
    )
    result = tempo_cli("log", "PROJ-1", "1h", "-d", "2026-01-05", "--yes")
    assert result.code == 1
    assert "required" in result.error["message"]
    assert result.error["service"] == "tempo"


def test_unknown_issue(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{JIRA}/issue/PROJ-9", status=404, json={"errorMessages": ["Issue does not exist"]})
    result = tempo_cli("log", "PROJ-9", "1h", "-d", "2026-01-05", "--yes")
    assert result.code == 1
    assert result.error["service"] == "jira"


# --------------------------------------------------------------------------- log-batch


def test_log_batch_json(tempo_cli: Invoke, api: responses.RequestsMock, tmp_path: Path) -> None:
    mock_issue(api, "PROJ-1", 10001)
    mock_issue(api, "PROJ-2", 10002)
    mock_existing(api)
    api.post(f"{TEMPO}/worklogs", json=worklog_json(1))
    file = tmp_path / "week.json"
    file.write_text(
        json.dumps(
            [
                {"issue": "PROJ-1", "duration": "4h", "date": "2026-01-05", "description": "A"},
                {
                    "issue": "PROJ-2",
                    "duration": "3h30m",
                    "date": "2026-01-05",
                    "attributes": {"_Role_": "Dev"},
                },
            ]
        )
    )
    dry = tempo_cli("log-batch", str(file), "--dry-run")
    assert len(dry.json["request"]["bodies"]) == 2
    result = tempo_cli("log-batch", str(file), "--yes")
    assert result.code == 0, result.err
    assert result.json["created"] == 2
    created = bodies(api, "POST", "/worklogs")
    assert created[1]["attributes"] == [{"key": "_Role_", "value": "Dev"}]


def test_log_batch_csv_stdin_daily_limit(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_issue(api)
    mock_existing(api)
    csv_text = "issue,duration,date\nPROJ-1,8h,2026-01-05\nPROJ-1,7h,2026-01-05\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(csv_text))
    result = tempo_cli("log-batch", "-", "--yes")
    assert result.code == 4
    assert "daily limit" in result.error["message"]
    assert not bodies(api, "POST", "/worklogs")


def test_log_batch_invalid_entry(
    tempo_cli: Invoke, api: responses.RequestsMock, tmp_path: Path
) -> None:
    file = tmp_path / "w.json"
    file.write_text(json.dumps([{"issue": "PROJ-1", "duration": "1h", "colour": "red"}]))
    result = tempo_cli("log-batch", str(file), "--yes")
    assert result.code == 3
    assert "Entry 1" in result.error["message"]
    file.write_text(json.dumps([{"issue": "PROJ-1"}]))
    assert tempo_cli("log-batch", str(file), "--yes").code == 3
    file.write_text("[]")
    assert tempo_cli("log-batch", str(file), "--yes").code == 3
    file.write_text("{bad")
    assert tempo_cli("log-batch", str(file), "--yes").code == 3
    assert tempo_cli("log-batch", str(tmp_path / "missing.json"), "--yes").code == 3
    mock_issue(api)
    file.write_text(json.dumps([{"issue": "PROJ-1", "duration": "1h", "date": "nope"}]))
    result = tempo_cli("log-batch", str(file), "--yes")
    assert result.error["message"].startswith("Entry 1:")


def test_log_batch_partial_failure(
    tempo_cli: Invoke, api: responses.RequestsMock, tmp_path: Path
) -> None:
    mock_issue(api)
    mock_existing(api)
    api.post(f"{TEMPO}/worklogs", json=worklog_json(1))
    api.post(f"{TEMPO}/worklogs", status=400, json={"errors": [{"message": "Period closed"}]})
    file = tmp_path / "w.json"
    file.write_text(
        json.dumps(
            {
                "worklogs": [
                    {"issue": "PROJ-1", "duration": "1h", "date": "2026-01-05"},
                    {"issue": "PROJ-1", "duration": "2h", "date": "2026-01-06"},
                ]
            }
        )
    )
    result = tempo_cli("log-batch", str(file), "--yes")
    assert result.code == 1
    assert result.json["created"] == 1
    assert result.json["results"][1]["error"] == "Period closed"
    assert result.error["reason"] == "partialFailure"


# --------------------------------------------------------------------------- worklogs


def test_worklogs_list(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    mock_issue(api)
    api.post(
        f"{TEMPO}/worklogs/search",
        json=page([worklog_json(1, seconds=3600), worklog_json(2, seconds=1800, day="2026-01-06")]),
    )
    api.post(f"{JIRA}/search/jql", json={"issues": [issue_json()]})
    api.get(f"{JIRA}/project/PROJ", json={"id": "100"})
    result = tempo_cli(
        "worklogs",
        "list",
        "--from",
        "2026-01-05",
        "--to",
        "2026-01-11",
        "--issue",
        "PROJ-1",
        "--project",
        "PROJ",
    )
    assert result.code == 0, result.err
    data = result.json
    assert data["count"] == 2
    assert data["totalSeconds"] == 5400
    assert data["total"] == "1h 30m"
    assert data["worklogs"][0]["issue"] == "PROJ-1"
    assert data["worklogs"][0]["summary"] == "Fix bug"
    search = bodies(api, "POST", "/worklogs/search")[0]
    assert search["from"] == "2026-01-05"
    assert search["authorIds"] == [ME]
    assert search["issueIds"] == [10001]
    assert search["projectIds"] == [100]


def test_worklogs_list_all_users_raw_limit(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.post(f"{TEMPO}/worklogs/search", json=page([worklog_json(1)], next_url="more"))
    result = tempo_cli("--raw", "worklogs", "list", "-p", "today", "-u", "all", "-n", "1")
    assert result.json["worklogs"][0]["tempoWorklogId"] == 1
    assert result.json["truncated"] is True
    assert "authorIds" not in bodies(api, "POST", "/worklogs/search")[0]


def test_worklogs_get(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{TEMPO}/worklogs/5",
        json=worklog_json(
            5, attributes={"self": "x", "values": [{"key": "_Role_", "value": "Dev"}]}
        ),
    )
    api.post(f"{JIRA}/search/jql", json={"issues": [issue_json()]})
    result = tempo_cli("worklogs", "get", "5")
    assert result.json["attributes"] == {"_Role_": "Dev"}
    assert tempo_cli("worklogs", "get", "x5").code == 3


def test_worklogs_update(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{TEMPO}/worklogs/5",
        json=worklog_json(
            5, seconds=3600, attributes={"self": "x", "values": [{"key": "_Role_", "value": "Dev"}]}
        ),
    )
    api.get(f"{JIRA}/issue/10001", json=issue_json())
    mock_existing(api, [worklog_json(5, seconds=3600)])
    api.put(f"{TEMPO}/worklogs/5", json=worklog_json(5, seconds=7200))
    api.post(f"{JIRA}/search/jql", json={"issues": [issue_json()]})
    result = tempo_cli(
        "worklogs", "update", "5", "--duration", "2h", "-a", "_Account_=ACC", "--yes"
    )
    assert result.code == 0, result.err
    body = bodies(api, "PUT", "/worklogs/5")[0]
    assert body["timeSpentSeconds"] == 7200
    assert body["billableSeconds"] == 7200  # followed the duration
    assert body["description"] == "Work"
    assert body["startTime"] == "09:00:00"
    assert {"key": "_Role_", "value": "Dev"} in body["attributes"]
    assert {"key": "_Account_", "value": "ACC"} in body["attributes"]


def test_worklogs_update_dry_run_and_policy(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.get(f"{TEMPO}/worklogs/5", json=worklog_json(5, billableSeconds=0))
    api.get(f"{JIRA}/issue/10001", json=issue_json())
    result = tempo_cli("worklogs", "update", "5", "-m", "New text", "--dry-run")
    body = result.json["request"]["body"]
    assert body["description"] == "New text"
    assert body["billableSeconds"] == 0
    monkeypatch.setenv("TEMPO_ALLOW_PROJECTS", "OTHER")
    assert tempo_cli("worklogs", "update", "5", "-m", "x", "--yes").code == 4


def test_worklogs_update_other_author(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{TEMPO}/worklogs/5", json=worklog_json(5, author="someone-else-1"))
    assert tempo_cli("worklogs", "update", "5", "-m", "x", "--yes").code == 4


def test_worklogs_delete(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{TEMPO}/worklogs/5", json=worklog_json(5))
    api.get(f"{JIRA}/issue/10001", json=issue_json())
    api.delete(f"{TEMPO}/worklogs/5", status=204)
    assert tempo_cli("worklogs", "delete", "5").code == 4
    result = tempo_cli("worklogs", "delete", "5", "--yes")
    assert result.json == {"deleted": 5}


# --------------------------------------------------------------------------- summary


def test_summary_by_day(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.post(
        f"{TEMPO}/worklogs/search",
        json=page(
            [
                worklog_json(1, day="2026-01-05", seconds=8 * 3600),
                worklog_json(2, day="2026-01-06", seconds=3 * 3600),
            ]
        ),
    )
    api.get(
        f"{TEMPO}/user-schedule",
        match=[matchers.query_param_matcher({"from": "2026-01-05", "to": "2026-01-07"})],
        json={
            "self": "x",
            "metadata": {},
            "results": [
                {"date": "2026-01-05", "requiredSeconds": 28800, "type": "WORKING_DAY"},
                {"date": "2026-01-06", "requiredSeconds": 28800, "type": "WORKING_DAY"},
                {
                    "date": "2026-01-07",
                    "requiredSeconds": 0,
                    "type": "HOLIDAY",
                    "holiday": {"name": "Epiphany"},
                },
            ],
        },
    )
    result = tempo_cli("summary", "--from", "2026-01-05", "--to", "2026-01-07")
    assert result.code == 0, result.err
    data = result.json
    assert data["loggedSeconds"] == 11 * 3600
    assert data["missingSeconds"] == 5 * 3600
    assert data["daysMissing"] == ["2026-01-06"]
    assert data["days"][2]["holiday"] == "Epiphany"
    assert data["days"][1]["missing"] == "5h"


def test_summary_by_issue(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.post(
        f"{TEMPO}/worklogs/search",
        json=page(
            [
                worklog_json(1, issue_id=10001, seconds=3600),
                worklog_json(2, issue_id=10002, seconds=7200),
                worklog_json(3, issue_id=10001, seconds=1800),
            ]
        ),
    )
    api.post(
        f"{JIRA}/search/jql",
        json={"issues": [issue_json("PROJ-1", 10001), issue_json("PROJ-2", 10002, "Other")]},
    )
    result = tempo_cli("summary", "-p", "week", "--by", "issue")
    rows = result.json["issues"]
    assert [r["issue"] for r in rows] == ["PROJ-2", "PROJ-1"]
    assert rows[1]["seconds"] == 5400
    assert rows[1]["worklogs"] == 2


# --------------------------------------------------------------------------- other groups


def test_issues(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.post(f"{JIRA}/search/jql", json={"issues": [issue_json()]})
    result = tempo_cli("issues", "list", "--preset", "recent")
    assert result.json["issues"][0] == {
        "key": "PROJ-1",
        "id": 10001,
        "summary": "Fix bug",
        "status": "In Progress",
        "project": "PROJ",
    }
    assert "worklogAuthor" in result.json["jql"]
    result = tempo_cli("issues", "list", "-q", "login page", "--project", "proj")
    assert result.json["jql"] == 'project = PROJ AND text ~ "login page" ORDER BY updated DESC'
    assert tempo_cli("issues", "list", "-q", 'evil" OR x').code == 3
    assert tempo_cli("issues", "list", "--jql", "key = PROJ-1").json["jql"] == "key = PROJ-1"
    mock_issue(api)
    assert tempo_cli("issues", "get", "PROJ-1").json["key"] == "PROJ-1"


def test_attributes_and_accounts(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{TEMPO}/work-attributes",
        json=page(
            [
                {
                    "key": "_Role_",
                    "name": "Role",
                    "type": "STATIC_LIST",
                    "required": True,
                    "values": ["dev"],
                    "names": {"dev": "Developer"},
                    "self": "x",
                },
                {
                    "key": "_Note_",
                    "name": "Note",
                    "type": "INPUT_FIELD",
                    "required": False,
                    "self": "x",
                },
            ]
        ),
    )
    result = tempo_cli("attributes", "list", "--required")
    assert result.json["attributes"] == [
        {
            "key": "_Role_",
            "name": "Role",
            "type": "STATIC_LIST",
            "required": True,
            "values": [{"value": "dev", "name": "Developer"}],
        }
    ]
    api.get(
        f"{TEMPO}/accounts",
        json=page(
            [
                {"key": "A", "name": "Acme", "status": "OPEN", "customer": {"name": "Acme Inc"}},
                {"key": "B", "name": "Old", "status": "CLOSED"},
            ]
        ),
    )
    assert [a["key"] for a in tempo_cli("accounts", "list").json["accounts"]] == ["A"]
    assert len(tempo_cli("accounts", "list", "--status", "all").json["accounts"]) == 2


APPROVAL = {
    "self": "x",
    "period": {"from": "2026-01-01", "to": "2026-01-31"},
    "status": {"key": "OPEN"},
    "timeSpentSeconds": 3600,
    "requiredSeconds": 7200,
    "actions": {"submit": {"self": "x"}},
    "user": {"accountId": ME},
    "worklogs": {"self": "x"},
}


def test_approvals(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{TEMPO}/periods", json={"periods": [{"from": "2026-01-01", "to": "2026-01-31"}]})
    assert tempo_cli("approvals", "periods", "-p", "month").json["periods"][0]["to"] == "2026-01-31"
    api.get(f"{TEMPO}/timesheet-approvals/user/{ME}", json=APPROVAL)
    status = tempo_cli("approvals", "status", "-d", "2026-01-10").json
    assert status["status"] == "OPEN"
    assert status["canSubmit"] is True
    assert status["logged"] == "1h"
    api.get(
        f"{TEMPO}/timesheet-approvals/user/{ME}/reviewers",
        json={"results": [{"accountId": "rev-123456"}]},
    )
    assert tempo_cli("approvals", "reviewers").json["reviewers"][0]["accountId"] == "rev-123456"

    dry = tempo_cli(
        "approvals",
        "submit",
        "-d",
        "2026-01-10",
        "--reviewer",
        "rev-123456",
        "--comment",
        "ok",
        "--dry-run",
    )
    assert dry.json["request"]["body"] == {"reviewerAccountId": "rev-123456", "comment": "ok"}
    assert tempo_cli("approvals", "submit", "-d", "2026-01-10").code == 4
    api.post(
        f"{TEMPO}/timesheet-approvals/user/{ME}/submit",
        json={**APPROVAL, "status": {"key": "IN_REVIEW"}},
    )
    assert (
        tempo_cli("approvals", "submit", "-d", "2026-01-10", "--yes").json["status"] == "IN_REVIEW"
    )


def test_api_command(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{TEMPO}/work-attributes",
        match=[matchers.query_param_matcher({"limit": "1"})],
        json=page([]),
    )
    assert tempo_cli("api", "get", "/4/work-attributes", "-p", '{"limit": 1}').json["results"] == []
    assert tempo_cli("api", "GET", "myself", "--jira").json["accountId"] == ME
    assert tempo_cli("api", "DELETE", "worklogs/1").code == 4
    dry = tempo_cli("api", "POST", "worklogs", "-b", '{"x": 1}', "--dry-run")
    assert dry.json["request"]["body"] == {"x": 1}
    assert tempo_cli("api", "GET", "worklogs", "--dry-run").json["dryRun"] is True
    for bad in (
        ["GET", "../x"],
        ["GET", "w?x=1"],
        ["GET", "w", "-p", "[1]"],
        ["GET", "w", "-p", "{"],
    ):
        assert tempo_cli("api", *bad).code == 3
    api.get(f"{TEMPO}/periods", json=[{"from": "a"}])
    assert tempo_cli("api", "GET", "periods").json == {"result": [{"from": "a"}]}


def test_api_body_from_file_and_stdin(
    tempo_cli: Invoke, api: responses.RequestsMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "b.json"
    file.write_text('{"a": 1}')
    assert tempo_cli("api", "POST", "x", "-b", f"@{file}", "--dry-run").json["request"]["body"] == {
        "a": 1
    }
    monkeypatch.setattr("sys.stdin", io.StringIO('{"b": 2}'))
    assert tempo_cli("api", "POST", "x", "-b", "-", "--dry-run").json["request"]["body"] == {"b": 2}
    assert tempo_cli("api", "POST", "x", "-b", "@/nonexistent", "--dry-run").code == 3


# --------------------------------------------------------------------------- auth / config / schema


def test_auth_login_verifies_and_stores(
    tempo_cli: Invoke, api: responses.RequestsMock, tmp_path: Path
) -> None:
    api.get(f"{TEMPO}/user-schedule", json={"results": []})
    result = tempo_cli("auth", "login")
    assert result.code == 0, result.err
    assert result.json["jira"]["accountId"] == ME
    stored = json.loads((tmp_path / "config" / "credentials.json").read_text())
    assert stored["tempo_token"] == "tempo-secret"
    assert stored["account_id"] == ME
    assert stored["jira_url"] == "https://acme.atlassian.net"

    status = tempo_cli("auth", "status").json
    assert status["tempo"]["configured"] is True
    assert "secret" not in json.dumps(status)
    assert tempo_cli("auth", "status", "--check").json["jira"]["verified"] is True
    assert tempo_cli("auth", "logout").json["removed"] is True


def test_auth_login_bad_tempo_token(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{TEMPO}/user-schedule", status=401, body="<html>no</html>")
    result = tempo_cli("auth", "login", "--skip-jira")
    assert result.code == 2
    assert "region" in result.error["hint"]


def test_auth_login_bad_jira(tempo_cli: Invoke, creds: None) -> None:
    with responses.RequestsMock() as api:
        api.get(f"{TEMPO}/user-schedule", json={"results": []})
        api.get(f"{JIRA}/myself", status=401, json={"errorMessages": ["nope"]})
        result = tempo_cli("auth", "login")
    assert result.code == 2
    assert "Jira" in result.error["message"]


def test_auth_login_no_token(tempo_cli: Invoke) -> None:
    result = tempo_cli("auth", "login")
    assert result.code == 2


def test_auth_login_region_no_verify(
    tempo_cli: Invoke, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TEMPO_API_TOKEN", "t")
    result = tempo_cli("auth", "login", "--region", "eu", "--skip-jira", "--no-verify")
    assert result.json["tempo"]["baseUrl"] == "https://api.eu.tempo.io/4"
    monkeypatch.delenv("TEMPO_API_TOKEN")
    status = tempo_cli("auth", "status").json
    assert status["tempo"]["region"] == "eu"
    assert status["tempo"]["source"] == "store"
    result = tempo_cli("auth", "login", "--no-verify")
    assert result.code == 2  # Jira details missing


def test_config_and_schema(tempo_cli: Invoke) -> None:
    shown = tempo_cli("config", "show").json
    assert shown["policy"]["max_daily_hours"] == 14
    assert tempo_cli("config", "init").code == 0
    assert tempo_cli("config", "init").code == 3
    assert tempo_cli("config", "init", "--force").code == 0
    assert tempo_cli("config", "show").json["configLoaded"] is True

    schema = tempo_cli("schema").json
    names = {c["command"] for c in schema["commands"]}
    assert {"tempo log", "tempo log-batch", "tempo worklogs list", "tempo summary"} <= names
    assert schema["exitCodes"]["policy"] == 4
    assert tempo_cli("schema", "log").json["command"] == "tempo log"
    assert tempo_cli("schema", "nope").code == 3


def test_table_output(tempo_cli: Invoke, api: responses.RequestsMock) -> None:
    api.post(f"{TEMPO}/worklogs/search", json=page([worklog_json(1)]))
    api.post(f"{JIRA}/search/jql", json={"issues": [issue_json()]})
    result = tempo_cli("-f", "table", "worklogs", "list", "-p", "today")
    assert "PROJ-1" in result.out
    assert "total: 1h" in result.err


def test_internal_error(
    tempo_cli: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr("tempo_cli.clients.TempoClient.work_attributes", boom)
    result = tempo_cli("attributes", "list")
    assert result.code == 5
    assert "kaboom" in result.error["message"]
