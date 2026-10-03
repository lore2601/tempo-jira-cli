from __future__ import annotations

import json

import pytest
import requests
import responses
from responses import matchers

from tempo_cli.clients import JiraClient, TempoClient
from tempo_cli.errors import ApiError, NetworkError
from tests.conftest import JIRA, TEMPO, issue_json, page, worklog_json


def tempo() -> TempoClient:
    return TempoClient("tok", TEMPO, sleep=lambda _s: None)


def jira() -> JiraClient:
    return JiraClient("https://acme.atlassian.net", "me@example.com", "jt", sleep=lambda _s: None)


@responses.activate
def test_tempo_auth_header_and_pagination() -> None:
    responses.post(
        f"{TEMPO}/worklogs/search",
        match=[matchers.query_param_matcher({"offset": "0", "limit": "1000"})],
        json=page([worklog_json(1), worklog_json(2)], next_url="n"),
    )
    responses.post(
        f"{TEMPO}/worklogs/search",
        match=[matchers.query_param_matcher({"offset": "2", "limit": "1000"})],
        json=page([worklog_json(3)]),
    )
    result = tempo().search_worklogs(
        date_from="2026-01-01",
        date_to="2026-01-31",
        author_ids=["me"],
        issue_ids=[1],
        project_ids=[2],
        updated_from="2026-01-02",
    )
    assert [w["tempoWorklogId"] for w in result.items] == [1, 2, 3]
    assert not result.has_more
    first = responses.calls[0].request
    assert first.headers["Authorization"] == "Bearer tok"
    body = json.loads(first.body)
    assert body["authorIds"] == ["me"]
    assert body["issueIds"] == [1]
    assert body["projectIds"] == [2]
    assert body["updatedFrom"] == "2026-01-02"


@responses.activate
def test_tempo_collect_limit() -> None:
    responses.get(f"{TEMPO}/accounts", json=page([{"key": "A"}, {"key": "B"}], next_url="n"))
    result = tempo().accounts(limit=2)
    assert len(result.items) == 2
    assert result.has_more
    assert "limit=2" in responses.calls[0].request.url


@responses.activate
def test_retry_then_success_and_errors() -> None:
    responses.get(f"{TEMPO}/worklogs/5", status=503)
    responses.get(f"{TEMPO}/worklogs/5", json=worklog_json(5))
    assert tempo().get_worklog("5")["tempoWorklogId"] == 5

    responses.get(
        f"{TEMPO}/worklogs/6",
        status=400,
        json={"errors": [{"message": "Issue not found"}, {"message": "Bad date"}]},
    )
    with pytest.raises(ApiError) as info:
        tempo().get_worklog("6")
    assert info.value.message == "Issue not found; Bad date"
    assert info.value.to_dict()["error"]["service"] == "tempo"


@pytest.mark.parametrize(
    ("status", "body", "message", "hint"),
    [
        (400, {"errors": {"message": "'date' must be valid"}}, "'date' must be valid", "dates"),
        (401, "<html>Unauthorized</html>", "HTTP 401", "region"),
        (403, "<html>no</html>", "HTTP 403", "permissions"),
        (404, {"message": "Gone"}, "Gone", None),
        (500, "boom", "boom", "internal"),
    ],
)
@responses.activate
def test_tempo_error_formats(status: int, body: object, message: str, hint: str | None) -> None:
    client = TempoClient("tok", TEMPO, max_retries=0)
    if isinstance(body, dict):
        responses.get(f"{TEMPO}/worklogs/1", status=status, json=body)
    else:
        responses.get(f"{TEMPO}/worklogs/1", status=status, body=str(body))
    with pytest.raises(ApiError) as info:
        client.get_worklog("1")
    assert info.value.message == message
    if hint:
        assert hint in (info.value.hint or "")


@responses.activate
def test_jira_error_format() -> None:
    client = JiraClient("https://acme.atlassian.net", "e", "t", max_retries=0)
    responses.get(
        f"{JIRA}/issue/NOPE-1",
        status=404,
        json={"errorMessages": ["Issue does not exist"], "errors": {}},
    )
    with pytest.raises(ApiError) as info:
        client.issue("NOPE-1")
    assert info.value.message == "Issue does not exist"
    assert "permission" in (info.value.hint or "")
    responses.get(f"{JIRA}/myself", status=401, json={"errors": {"field": "bad"}})
    with pytest.raises(ApiError, match="field: bad"):
        client.myself()


@responses.activate
def test_network_error() -> None:
    client = TempoClient("tok", TEMPO, max_retries=1, sleep=lambda _s: None)
    responses.get(f"{TEMPO}/worklogs/1", body=requests.ConnectionError("down"))
    with pytest.raises(NetworkError):
        client.get_worklog("1")


@responses.activate
def test_jira_issue_cache_and_bulk() -> None:
    responses.get(f"{JIRA}/issue/PROJ-1", json=issue_json("PROJ-1", 10001))
    client = jira()
    assert client.issue("PROJ-1")["id"] == "10001"
    assert client.issue("10001")["key"] == "PROJ-1"  # cached by id
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")

    responses.post(
        f"{JIRA}/search/jql",
        match=[
            matchers.json_params_matcher(
                {
                    "jql": "id in (10002,10003)",
                    "fields": ["summary", "project", "status"],
                    "maxResults": 2,
                }
            )
        ],
        json={"issues": [issue_json("PROJ-2", 10002)]},
    )
    found = client.issues_by_ids([10001, 10002, "10003", "x"])
    assert set(found) == {"10001", "10002"}


@responses.activate
def test_jira_search_pagination_and_project() -> None:
    responses.post(
        f"{JIRA}/search/jql", json={"issues": [issue_json("A-1", 1)], "nextPageToken": "t"}
    )
    responses.post(f"{JIRA}/search/jql", json={"issues": [issue_json("A-2", 2)]})
    client = jira()
    assert [i["key"] for i in client.search("project = A", limit=5)] == ["A-1", "A-2"]
    assert json.loads(responses.calls[1].request.body)["nextPageToken"] == "t"
    responses.get(f"{JIRA}/project/A", json={"id": "100", "key": "A"})
    assert client.project("A")["id"] == "100"
    client.project("A")
    assert len(responses.calls) == 3


def test_backoff() -> None:
    assert TempoClient._backoff(0, "3") == 3.0
    assert TempoClient._backoff(0, "999") == 60.0
    assert 1 <= TempoClient._backoff(0, "later") < 2
    assert TempoClient._backoff(9, None) == 30.0
