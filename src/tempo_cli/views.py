"""Compact projections of Tempo resources (``--raw`` returns the API objects)."""

from __future__ import annotations

from typing import Any

from tempo_cli.validation import format_duration


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in (None, "", [], {})}


def worklog(w: dict[str, Any], issues: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    issue_id = str((w.get("issue") or {}).get("id") or "")
    issue = (issues or {}).get(issue_id) or {}
    fields = issue.get("fields") or {}
    spent = w.get("timeSpentSeconds")
    billable = w.get("billableSeconds")
    attributes = {
        a.get("key"): a.get("value") for a in (w.get("attributes") or {}).get("values") or []
    }
    return _drop_empty(
        {
            "id": w.get("tempoWorklogId"),
            "issue": issue.get("key") or (int(issue_id) if issue_id.isdigit() else None),
            "issueId": int(issue_id) if issue_id.isdigit() else None,
            "summary": fields.get("summary"),
            "date": w.get("startDate"),
            "start": (w.get("startTime") or None),
            "duration": format_duration(spent),
            "seconds": spent,
            "billableSeconds": billable if billable is not None and billable != spent else None,
            "description": w.get("description"),
            "author": (w.get("author") or {}).get("accountId"),
            "attributes": attributes,
            "updatedAt": w.get("updatedAt"),
        }
    )


def issue(i: dict[str, Any]) -> dict[str, Any]:
    fields = i.get("fields") or {}
    return _drop_empty(
        {
            "key": i.get("key"),
            "id": int(i["id"]) if str(i.get("id", "")).isdigit() else i.get("id"),
            "summary": fields.get("summary"),
            "status": (fields.get("status") or {}).get("name"),
            "project": (fields.get("project") or {}).get("key"),
        }
    )


def work_attribute(a: dict[str, Any]) -> dict[str, Any]:
    names = a.get("names") or {}
    values = a.get("values") or []
    return _drop_empty(
        {
            "key": a.get("key"),
            "name": a.get("name"),
            "type": a.get("type"),
            "required": bool(a.get("required")),
            "values": [{"value": v, "name": names.get(v, v)} for v in values],
        }
    )


def account(a: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "key": a.get("key"),
            "name": a.get("name"),
            "status": a.get("status"),
            "global": a.get("global"),
            "customer": (a.get("customer") or {}).get("name"),
            "category": (a.get("category") or {}).get("name"),
        }
    )


def approval(a: dict[str, Any]) -> dict[str, Any]:
    status = a.get("status") or {}
    period = a.get("period") or {}
    return _drop_empty(
        {
            "from": period.get("from"),
            "to": period.get("to"),
            "status": status.get("key"),
            "logged": format_duration(a.get("timeSpentSeconds")),
            "required": format_duration(a.get("requiredSeconds")),
            "timeSpentSeconds": a.get("timeSpentSeconds"),
            "requiredSeconds": a.get("requiredSeconds"),
            "reviewer": (a.get("reviewer") or {}).get("accountId"),
            "comment": status.get("comment"),
            "canSubmit": "submit" in (a.get("actions") or {}),
        }
    )
