"""HTTP clients for the Tempo REST API (v4) and the Jira Cloud REST API (v3).

Tempo identifies issues and users by numeric issue id and Atlassian account id
only, so a small Jira client resolves issue keys, project keys and the current
user. Transient failures (429, 5xx, network) are retried with backoff.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from tempo_cli import __version__
from tempo_cli.errors import ApiError, NetworkError, TempoCliError

USER_AGENT = f"tempo-jira-cli/{__version__}"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
TEMPO_PAGE_SIZE = 1000
JIRA_ISSUE_FIELDS = ["summary", "project", "status"]


@dataclass
class Page:
    items: list[dict[str, Any]]
    has_more: bool = False


def _seg(value: str) -> str:
    """Encode a single URL path segment."""
    return quote(str(value), safe="")


class HttpClient:
    service = "http"

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.session = session
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.session.headers.setdefault("Accept", "application/json")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return float(min(2**attempt + random.random(), 30.0))  # noqa: S311 - jitter only

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        body: Any = None,
    ) -> Any:
        """Call ``{base_url}{path}`` and return decoded JSON (``{}`` for empty bodies)."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        if isinstance(params, dict):
            params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, params=params or None, json=body, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise NetworkError(f"Cannot reach {self.service}: {exc}") from exc
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if not response.ok:
                raise ApiError.from_response(response, self.service)
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise TempoCliError(f"{self.service} returned a non-JSON response") from exc
        raise AssertionError("unreachable")  # pragma: no cover


class TempoClient(HttpClient):
    service = "tempo"

    def __init__(self, token: str, base_url: str, **kwargs: Any) -> None:
        session = kwargs.pop("session", None) or requests.Session()
        session.headers["Authorization"] = f"Bearer {token}"
        super().__init__(session, base_url, **kwargs)

    def collect(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        limit: int | None = None,
    ) -> Page:
        """Follow offset/limit pagination until ``limit`` items (``None`` = all)."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page_size = (
                TEMPO_PAGE_SIZE if limit is None else min(limit - len(items), TEMPO_PAGE_SIZE)
            )
            data = self.request(
                method,
                path,
                params={**(params or {}), "offset": offset, "limit": page_size},
                body=body,
            )
            results = list(data.get("results") or [])
            items.extend(results)
            has_next = bool((data.get("metadata") or {}).get("next")) and bool(results)
            if limit is not None and len(items) >= limit:
                return Page(items[:limit], has_next or len(items) > limit)
            if not has_next:
                return Page(items, False)
            offset += len(results)

    # ------------------------------------------------------------------ worklogs

    def search_worklogs(
        self,
        *,
        date_from: str,
        date_to: str,
        author_ids: Iterable[str] = (),
        issue_ids: Iterable[int] = (),
        project_ids: Iterable[int] = (),
        updated_from: str | None = None,
        limit: int | None = None,
    ) -> Page:
        body: dict[str, Any] = {"from": date_from, "to": date_to}
        if author_ids:
            body["authorIds"] = list(author_ids)
        if issue_ids:
            body["issueIds"] = list(issue_ids)
        if project_ids:
            body["projectIds"] = list(project_ids)
        if updated_from:
            body["updatedFrom"] = updated_from
        body["orderBy"] = [{"field": "START_DATE_TIME", "order": "ASC"}]
        return self.collect("POST", "worklogs/search", body=body, limit=limit)

    def get_worklog(self, worklog_id: str) -> dict[str, Any]:
        return dict(self.request("GET", f"worklogs/{_seg(worklog_id)}"))

    def create_worklog(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self.request("POST", "worklogs", body=body))

    def update_worklog(self, worklog_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self.request("PUT", f"worklogs/{_seg(worklog_id)}", body=body))

    def delete_worklog(self, worklog_id: str) -> None:
        self.request("DELETE", f"worklogs/{_seg(worklog_id)}")

    # ------------------------------------------------------------------ other resources

    def work_attributes(self) -> list[dict[str, Any]]:
        return self.collect("GET", "work-attributes").items

    def accounts(self, limit: int | None = None) -> Page:
        return self.collect("GET", "accounts", limit=limit)

    def user_schedule(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        data = self.request("GET", "user-schedule", params={"from": date_from, "to": date_to})
        return list(data.get("results") or [])

    def periods(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        data = self.request("GET", "periods", params={"from": date_from, "to": date_to})
        return list(data.get("periods") or [])

    def approval(self, account_id: str, date_from: str, date_to: str | None) -> dict[str, Any]:
        return dict(
            self.request(
                "GET",
                f"timesheet-approvals/user/{_seg(account_id)}",
                params={"from": date_from, "to": date_to},
            )
        )

    def approval_reviewers(self, account_id: str) -> list[dict[str, Any]]:
        data = self.request("GET", f"timesheet-approvals/user/{_seg(account_id)}/reviewers")
        return list(data.get("results") or [])

    def submit_approval(
        self, account_id: str, date_from: str, date_to: str | None, body: dict[str, Any]
    ) -> dict[str, Any]:
        return dict(
            self.request(
                "POST",
                f"timesheet-approvals/user/{_seg(account_id)}/submit",
                params={"from": date_from, "to": date_to},
                body=body,
            )
        )


class JiraClient(HttpClient):
    service = "jira"

    def __init__(self, url: str, email: str, token: str, **kwargs: Any) -> None:
        session = kwargs.pop("session", None) or requests.Session()
        session.auth = (email, token)
        super().__init__(session, f"{url.rstrip('/')}/rest/api/3", **kwargs)
        self._issues: dict[str, dict[str, Any]] = {}
        self._projects: dict[str, dict[str, Any]] = {}

    def myself(self) -> dict[str, Any]:
        return dict(self.request("GET", "myself"))

    def _remember(self, issue: dict[str, Any]) -> dict[str, Any]:
        self._issues[str(issue["id"])] = issue
        self._issues[str(issue["key"])] = issue
        return issue

    def issue(self, key_or_id: str) -> dict[str, Any]:
        """Return ``{"id", "key", "fields": {...}}`` for an issue key or numeric id."""
        cached = self._issues.get(key_or_id)
        if cached:
            return cached
        data = self.request(
            "GET", f"issue/{_seg(key_or_id)}", params={"fields": ",".join(JIRA_ISSUE_FIELDS)}
        )
        return self._remember(dict(data))

    def issues_by_ids(self, ids: Iterable[int | str]) -> dict[str, dict[str, Any]]:
        """Resolve many issue ids at once (missing or invisible issues are skipped)."""
        wanted = sorted({str(i) for i in ids if str(i).isdigit()})
        missing = [i for i in wanted if i not in self._issues]
        for start in range(0, len(missing), 100):
            chunk = missing[start : start + 100]
            for issue in self.search(f"id in ({','.join(chunk)})", limit=len(chunk)):
                self._remember(issue)
        return {i: self._issues[i] for i in wanted if i in self._issues}

    def search(self, jql: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Run a JQL search with the enhanced ``/search/jql`` endpoint."""
        issues: list[dict[str, Any]] = []
        token: str | None = None
        while len(issues) < limit:
            body: dict[str, Any] = {
                "jql": jql,
                "fields": JIRA_ISSUE_FIELDS,
                "maxResults": min(limit - len(issues), 100),
            }
            if token:
                body["nextPageToken"] = token
            data = self.request("POST", "search/jql", body=body)
            batch = list(data.get("issues") or [])
            issues.extend(batch)
            token = data.get("nextPageToken")
            if not token or not batch:
                break
        return [self._remember(i) for i in issues[:limit]]

    def project(self, key: str) -> dict[str, Any]:
        if key not in self._projects:
            self._projects[key] = dict(self.request("GET", f"project/{_seg(key)}"))
        return self._projects[key]
