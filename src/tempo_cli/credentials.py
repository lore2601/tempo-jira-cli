"""Tempo and Jira credentials: resolution, storage and region handling.

Resolution order for every field: environment variable, then the stored
credentials written by ``tempo auth login``.

=====================  ==========================================
Variable               Meaning
=====================  ==========================================
``TEMPO_API_TOKEN``    Tempo personal token (Settings → API integration)
``TEMPO_REGION``       ``eu``, ``us`` or ``global``
``TEMPO_BASE_URL``     Full API base URL (overrides the region)
``JIRA_URL``           Jira site, e.g. ``https://acme.atlassian.net``
``JIRA_EMAIL``         Atlassian account email
``JIRA_API_TOKEN``     Atlassian API token
``TEMPO_ACCOUNT_ID``   Your Atlassian account id (skips a Jira lookup)
=====================  ==========================================
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from tempo_cli import config
from tempo_cli.errors import AuthError, ValidationError

REGIONS: dict[str, str] = {
    "eu": "https://api.eu.tempo.io/4",
    "us": "https://api.us.tempo.io/4",
    "global": "https://api.tempo.io/4",
}
KEYRING_SERVICE = "tempo-jira-cli"
KEYRING_USER = "default"
_JIRA_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?$")


def normalise_jira_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    if not _JIRA_URL_RE.match(url):
        raise ValidationError(
            f"Invalid Jira URL: {value!r}", hint="Expected e.g. https://acme.atlassian.net"
        )
    return url


def base_url_for(region: str) -> str:
    if region not in REGIONS:
        raise ValidationError(f"Unknown region {region!r}", hint="Use eu, us or global.")
    return REGIONS[region]


@dataclass
class Credentials:
    tempo_token: str | None = None
    region: str = "global"
    base_url: str | None = None
    jira_url: str | None = None
    jira_email: str | None = None
    jira_token: str | None = None
    account_id: str | None = None
    display_name: str | None = None
    time_zone: str | None = None
    sources: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def tempo_base_url(self) -> str:
        return (self.base_url or base_url_for(self.region)).rstrip("/")

    @property
    def has_jira(self) -> bool:
        return bool(self.jira_url and self.jira_email and self.jira_token)

    def stored_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("sources", None)
        return {k: v for k, v in data.items() if v is not None}


class CredentialStore:
    """Stores credentials in a 0600 JSON file, or in the OS keyring."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env
        backend = self.env.get("TEMPO_TOKEN_STORE", "file").strip().lower()
        if backend not in {"file", "keyring"}:
            raise ValidationError("TEMPO_TOKEN_STORE must be 'file' or 'keyring'")
        self.backend = backend
        self.path = config.credentials_file(self.env)

    @property
    def location(self) -> str:
        return f"keyring:{KEYRING_SERVICE}" if self.backend == "keyring" else str(self.path)

    def _keyring(self) -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise AuthError(
                "TEMPO_TOKEN_STORE=keyring requires the optional 'keyring' package",
                hint="Install it with: pipx install 'tempo-jira-cli[keyring]'",
            ) from exc
        return keyring

    def load(self) -> dict[str, Any]:
        if self.backend == "keyring":
            raw = self._keyring().get_password(KEYRING_SERVICE, KEYRING_USER)
        elif self.path.is_file():
            raw = self.path.read_text(encoding="utf-8")
        else:
            raw = None
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"Stored credentials at {self.location} are corrupted",
                hint="Run `tempo auth logout` and `tempo auth login` again.",
            ) from exc
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2)
        if self.backend == "keyring":
            self._keyring().set_password(KEYRING_SERVICE, KEYRING_USER, payload)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cred-", suffix=".json")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def delete(self) -> bool:
        if self.backend == "keyring":
            keyring = self._keyring()
            if keyring.get_password(KEYRING_SERVICE, KEYRING_USER) is None:
                return False
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            return True
        if self.path.is_file():
            self.path.unlink()
            return True
        return False


_ENV_MAP = {
    "tempo_token": "TEMPO_API_TOKEN",
    "region": "TEMPO_REGION",
    "base_url": "TEMPO_BASE_URL",
    "jira_url": "JIRA_URL",
    "jira_email": "JIRA_EMAIL",
    "jira_token": "JIRA_API_TOKEN",
    "account_id": "TEMPO_ACCOUNT_ID",
}


def resolve(env: Mapping[str, str] | None = None) -> Credentials:
    """Merge environment variables over stored credentials."""
    env = os.environ if env is None else env
    stored = CredentialStore(env).load()
    creds = Credentials()
    for name in (
        "tempo_token",
        "region",
        "base_url",
        "jira_url",
        "jira_email",
        "jira_token",
        "account_id",
        "display_name",
        "time_zone",
    ):
        var = _ENV_MAP.get(name)
        if var and env.get(var):
            setattr(creds, name, env[var])
            creds.sources[name] = f"env:{var}"
        elif stored.get(name):
            setattr(creds, name, stored[name])
            creds.sources[name] = "store"
    creds.region = creds.region.strip().lower()
    base_url_for(creds.region)  # validate
    if creds.jira_url:
        creds.jira_url = normalise_jira_url(creds.jira_url)
    if creds.account_id and creds.sources.get("account_id", "").startswith("env"):
        from tempo_cli import validation

        validation.account_id(creds.account_id)
    return creds


def require_tempo(creds: Credentials) -> str:
    if not creds.tempo_token:
        raise AuthError(
            "No Tempo API token configured",
            hint="Run `tempo auth login` or set TEMPO_API_TOKEN "
            "(Tempo → Settings → API integration).",
        )
    return creds.tempo_token


def require_jira(creds: Credentials, why: str) -> None:
    if not creds.has_jira:
        raise AuthError(
            f"Jira credentials are needed to {why}",
            hint="Run `tempo auth login` or set JIRA_URL, JIRA_EMAIL and JIRA_API_TOKEN "
            "(https://id.atlassian.com/manage-profile/security/api-tokens).",
        )
