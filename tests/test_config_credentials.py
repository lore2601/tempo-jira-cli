from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from tempo_cli import config, credentials
from tempo_cli.errors import AuthError, PolicyError, ValidationError


def write_config(tmp_path: Path, body: str) -> dict[str, str]:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return {"TEMPO_CONFIG": str(path), "TEMPO_CONFIG_DIR": str(tmp_path)}


def test_default_policy(tmp_path: Path) -> None:
    cfg = config.load_config({"TEMPO_CONFIG_DIR": str(tmp_path)})
    assert cfg.source is None
    policy = cfg.policy
    policy.require_writable()
    policy.require_project("ANY")
    policy.require_worklog_length(12 * 3600)
    with pytest.raises(PolicyError):
        policy.require_worklog_length(12 * 3600 + 1)
    policy.require_daily_total("2026-01-01", 14 * 3600)
    with pytest.raises(PolicyError):
        policy.require_daily_total("2026-01-01", 14 * 3600 + 60)


def test_file_and_env_policy(tmp_path: Path) -> None:
    env = write_config(
        tmp_path,
        '[policy]\nprojects = ["abc", "DEF"]\nmax_worklog_hours = 8\n'
        '[defaults]\nstart_time = "09:00"\n',
    )
    cfg = config.load_config(env)
    assert cfg.defaults["start_time"] == "09:00"
    cfg.policy.require_project("ABC")
    with pytest.raises(PolicyError):
        cfg.policy.require_project("XYZ")
    assert cfg.policy.max_worklog_hours == 8

    env.update(
        {"TEMPO_READ_ONLY": "yes", "TEMPO_ALLOW_PROJECTS": "*", "TEMPO_MAX_DAILY_HOURS": "9"}
    )
    cfg = config.load_config(env)
    with pytest.raises(PolicyError, match="read-only"):
        cfg.policy.require_writable()
    cfg.policy.require_project("XYZ")
    assert cfg.policy.as_dict()["max_daily_hours"] == 9


@pytest.mark.parametrize(
    "body",
    [
        "[policy]\nbogus = 1\n",
        "[policy]\nmax_daily_hours = 30\n",
        "[policy]\nmax_daily_hours = 'x'\n",
        "[policy]\nprojects = 1\n",
        "[policy]\nprojects = ['bad key']\n",
        "[policy]\nread_only = 'maybe'\n",
        "policy = 1\n",
        "defaults = 1\n",
        "[[[",
    ],
)
def test_invalid_config(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValidationError):
        config.load_config(write_config(tmp_path, body))


def test_sample_config_valid(tmp_path: Path) -> None:
    assert config.load_config(write_config(tmp_path, config.SAMPLE_CONFIG)).source is not None


def test_paths(tmp_path: Path) -> None:
    assert (
        config.credentials_file({"TEMPO_CONFIG_DIR": str(tmp_path)})
        == tmp_path / "credentials.json"
    )
    assert config.credentials_file({"TEMPO_CREDENTIALS_FILE": "/x/c.json"}) == Path("/x/c.json")
    assert config.config_dir({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "tempo-cli"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_store_roundtrip_permissions(tmp_path: Path) -> None:
    store = credentials.CredentialStore({"TEMPO_CONFIG_DIR": str(tmp_path)})
    assert store.load() == {}
    store.save({"tempo_token": "t"})
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert store.load() == {"tempo_token": "t"}
    assert store.delete()
    assert not store.delete()


def test_store_corrupted_and_backend(tmp_path: Path) -> None:
    env = {"TEMPO_CONFIG_DIR": str(tmp_path)}
    store = credentials.CredentialStore(env)
    tmp_path.mkdir(exist_ok=True)
    store.path.write_text("{oops")
    with pytest.raises(AuthError):
        store.load()
    with pytest.raises(ValidationError):
        credentials.CredentialStore({**env, "TEMPO_TOKEN_STORE": "vault"})


def test_resolve_env_over_store(tmp_path: Path) -> None:
    env = {"TEMPO_CONFIG_DIR": str(tmp_path)}
    credentials.CredentialStore(env).save(
        {
            "tempo_token": "stored",
            "region": "eu",
            "jira_url": "https://a.atlassian.net",
            "jira_email": "a@b.c",
            "jira_token": "j",
            "account_id": "acc-123456",
        }
    )
    creds = credentials.resolve({**env, "TEMPO_API_TOKEN": "fromenv"})
    assert creds.tempo_token == "fromenv"
    assert creds.sources["tempo_token"] == "env:TEMPO_API_TOKEN"
    assert creds.sources["region"] == "store"
    assert creds.tempo_base_url == "https://api.eu.tempo.io/4"
    assert creds.has_jira
    creds = credentials.resolve({**env, "TEMPO_BASE_URL": "https://example.test/4/"})
    assert creds.tempo_base_url == "https://example.test/4"


def test_resolve_validation(tmp_path: Path) -> None:
    env = {"TEMPO_CONFIG_DIR": str(tmp_path)}
    with pytest.raises(ValidationError):
        credentials.resolve({**env, "TEMPO_REGION": "mars"})
    with pytest.raises(ValidationError):
        credentials.resolve({**env, "JIRA_URL": "ftp://x"})
    with pytest.raises(ValidationError):
        credentials.resolve({**env, "TEMPO_ACCOUNT_ID": "../x"})
    assert credentials.normalise_jira_url("acme.atlassian.net/") == "https://acme.atlassian.net"


def test_require_helpers() -> None:
    empty = credentials.Credentials()
    with pytest.raises(AuthError, match="Tempo"):
        credentials.require_tempo(empty)
    with pytest.raises(AuthError, match="Jira"):
        credentials.require_jira(empty, "do things")
    assert credentials.Credentials(tempo_token="x").stored_dict() == {
        "tempo_token": "x",
        "region": "global",
    }
