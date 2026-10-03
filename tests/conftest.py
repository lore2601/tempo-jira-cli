from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import responses

from tempo_cli.cli import run

TEMPO = "https://api.tempo.io/4"
JIRA = "https://acme.atlassian.net/rest/api/3"
ME = "5b10ac8d82e05b22cc7d4ef5"

ENV_VARS = [
    "TEMPO_CONFIG",
    "TEMPO_CONFIG_DIR",
    "TEMPO_CREDENTIALS_FILE",
    "TEMPO_TOKEN_STORE",
    "TEMPO_FORMAT",
    "TEMPO_API_TOKEN",
    "TEMPO_REGION",
    "TEMPO_BASE_URL",
    "TEMPO_ACCOUNT_ID",
    "TEMPO_READ_ONLY",
    "TEMPO_ALLOW_PROJECTS",
    "TEMPO_MAX_WORKLOG_HOURS",
    "TEMPO_MAX_DAILY_HOURS",
    "TEMPO_ALLOW_FUTURE_DATES",
    "TEMPO_ALLOW_OTHER_AUTHORS",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
]


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def json(self) -> Any:
        return json.loads(self.out)

    @property
    def error(self) -> dict[str, Any]:
        return dict(json.loads(self.err.strip().splitlines()[-1])["error"])


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TEMPO_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr("tempo_cli.clients.time.sleep", lambda _s: None)


@pytest.fixture
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPO_API_TOKEN", "tempo-secret")
    monkeypatch.setenv("JIRA_URL", "acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "jira-secret")


@pytest.fixture
def api(creds: None) -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get(f"{JIRA}/myself", json={"accountId": ME, "displayName": "Me"})
        yield mock


def issue_json(
    key: str = "PROJ-1", issue_id: int = 10001, summary: str = "Fix bug"
) -> dict[str, Any]:
    project = key.split("-")[0]
    return {
        "id": str(issue_id),
        "key": key,
        "fields": {
            "summary": summary,
            "project": {"key": project, "id": "100"},
            "status": {"name": "In Progress"},
        },
    }


def worklog_json(
    wid: int = 1,
    issue_id: int = 10001,
    day: str = "2026-01-05",
    seconds: int = 3600,
    description: str = "Work",
    author: str = ME,
    **extra: Any,
) -> dict[str, Any]:
    data = {
        "self": f"{TEMPO}/worklogs/{wid}",
        "tempoWorklogId": wid,
        "issue": {"self": "x", "id": issue_id},
        "timeSpentSeconds": seconds,
        "billableSeconds": seconds,
        "startDate": day,
        "startTime": "09:00:00",
        "description": description,
        "createdAt": "2026-01-05T10:00:00Z",
        "updatedAt": "2026-01-05T10:00:00Z",
        "author": {"self": "x", "accountId": author},
        "attributes": {"self": "x", "values": []},
    }
    data.update(extra)
    return data


def page(results: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {"count": len(results), "offset": 0, "limit": 1000}
    if next_url:
        meta["next"] = next_url
    return {"self": "x", "metadata": meta, "results": results}


@pytest.fixture
def tempo_cli(capsys: pytest.CaptureFixture[str]) -> Callable[..., Result]:
    def invoke(*args: str) -> Result:
        code = run(list(args))
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return invoke
