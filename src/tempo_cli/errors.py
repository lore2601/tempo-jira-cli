"""Error types and stable exit codes.

Every failure surfaces as a :class:`TempoCliError` so the CLI can print one
machine-readable JSON error object and exit with a documented code.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

import requests


class ExitCode(IntEnum):
    """Process exit codes. These are part of the public interface."""

    OK = 0
    API = 1
    AUTH = 2
    VALIDATION = 3
    POLICY = 4
    INTERNAL = 5


class TempoCliError(Exception):
    """Base class for all expected errors."""

    exit_code: ExitCode = ExitCode.INTERNAL
    reason: str = "internal"

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if reason is not None:
            self.reason = reason
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "exitCode": int(self.exit_code),
            "reason": self.reason,
            "message": self.message,
        }
        if self.hint:
            error["hint"] = self.hint
        error.update(self.details)
        return {"error": error}


class ValidationError(TempoCliError):
    """Invalid user input (bad issue key, duration, date, ...)."""

    exit_code = ExitCode.VALIDATION
    reason = "invalidArgument"


class AuthError(TempoCliError):
    """Missing or rejected credentials."""

    exit_code = ExitCode.AUTH
    reason = "unauthenticated"


class PolicyError(TempoCliError):
    """The local policy refused the action."""

    exit_code = ExitCode.POLICY
    reason = "policyDenied"


class ConfirmationRequired(PolicyError):
    """A write was attempted non-interactively without ``--yes``."""

    reason = "confirmationRequired"


class NetworkError(TempoCliError):
    """The API could not be reached."""

    exit_code = ExitCode.API
    reason = "networkError"


class PartialFailure(TempoCliError):
    """Some operations of a batch failed."""

    exit_code = ExitCode.API
    reason = "partialFailure"


class ApiError(TempoCliError):
    """Tempo or Jira returned an error response."""

    exit_code = ExitCode.API
    reason = "apiError"

    def __init__(
        self,
        message: str,
        *,
        service: str,
        http_status: int,
        hint: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            message,
            hint=hint,
            reason=reason,
            details={"service": service, "httpStatus": http_status},
        )
        self.service = service
        self.http_status = http_status

    @classmethod
    def from_response(cls, response: requests.Response, service: str) -> ApiError:
        """Parse Tempo (``{"errors": ...}``) and Jira (``errorMessages``) error bodies."""
        messages: list[str] = []
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if isinstance(errors, list):
                messages += [
                    str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors
                ]
            elif isinstance(errors, dict):
                if "message" in errors:
                    messages.append(str(errors["message"]))
                else:
                    messages += [f"{k}: {v}" for k, v in errors.items()]
            messages += [str(m) for m in payload.get("errorMessages") or []]
            if not messages and payload.get("message"):
                messages.append(str(payload["message"]))
        if not messages:
            text = (response.text or "").strip()
            if text and not text.lstrip().startswith("<"):
                messages.append(text[:500])
        message = "; ".join(messages) or f"HTTP {response.status_code}"
        return cls(
            message,
            service=service,
            http_status=response.status_code,
            reason=_reason(response.status_code),
            hint=_hint(service, response.status_code),
        )


def _reason(code: int) -> str:
    return {
        400: "badRequest",
        401: "unauthorized",
        403: "forbidden",
        404: "notFound",
        409: "conflict",
        429: "rateLimited",
    }.get(code, "serverError" if code >= 500 else "apiError")


def _hint(service: str, code: int) -> str | None:
    if service == "tempo":
        if code == 401:
            return (
                "Tempo rejected the token. Check it, and check the region: a token from the "
                "EU cluster only works with --region eu. Run `tempo auth login`."
            )
        if code == 403:
            return "Your Tempo permissions do not allow this (e.g. closed period or other user)."
        if code == 400:
            return "Tempo rejected the request: check dates, durations and required attributes."
    if service == "jira":
        if code == 401:
            return (
                "Jira rejected the credentials. Check JIRA_EMAIL / JIRA_API_TOKEN and the site URL."
            )
        if code == 404:
            return "Not found in Jira, or you do not have permission to see it."
    if code == 429:
        return "Rate limited. Wait a moment and retry."
    if code >= 500:
        return "The service had an internal error. Retry later."
    return None
