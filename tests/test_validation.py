from __future__ import annotations

from datetime import date

import pytest

from tempo_cli import validation
from tempo_cli.errors import ValidationError

TODAY = date(2026, 1, 14)  # a Wednesday


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("1h", 3600),
        ("1h30m", 5400),
        ("1h 30m", 5400),
        ("1.5h", 5400),
        ("1,5h", 5400),
        ("90m", 5400),
        ("1:30", 5400),
        ("45m", 2700),
        ("3600s", 3600),
        ("2H", 7200),
        ("0.25h", 900),
    ],
)
def test_parse_duration(value: str, seconds: int) -> None:
    assert validation.parse_duration(value) == seconds


@pytest.mark.parametrize("value", ["", "2", "abc", "1x", "h1", "0m", "25h", "1h-", "-1h"])
def test_parse_duration_rejects(value: str) -> None:
    with pytest.raises(ValidationError):
        validation.parse_duration(value)


def test_parse_duration_allow_zero() -> None:
    assert validation.parse_duration("0m", allow_zero=True) == 0


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (5400, "1h 30m"),
        (3600, "1h"),
        (60, "1m"),
        (30, "30s"),
        (0, "0m"),
        (None, ""),
        (-900, "-15m"),
    ],
)
def test_format_duration(seconds: int | None, text: str) -> None:
    assert validation.format_duration(seconds) == text


def test_hours() -> None:
    assert validation.hours(5400) == 1.5
    assert validation.hours(None) == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("today", date(2026, 1, 14)),
        ("oggi", date(2026, 1, 14)),
        ("yesterday", date(2026, 1, 13)),
        ("ieri", date(2026, 1, 13)),
        ("-2d", date(2026, 1, 12)),
        ("+1d", date(2026, 1, 15)),
        ("monday", date(2026, 1, 12)),
        ("wednesday", date(2026, 1, 14)),
        ("friday", date(2026, 1, 9)),
        ("2026-01-02", date(2026, 1, 2)),
    ],
)
def test_parse_date(value: str, expected: date) -> None:
    assert validation.parse_date(value, today=TODAY) == expected


def test_parse_date_rejects() -> None:
    with pytest.raises(ValidationError):
        validation.parse_date("next week", today=TODAY)


@pytest.mark.parametrize(
    ("value", "expected"), [("9:30", "09:30:00"), ("09:30:15", "09:30:15"), ("23:59", "23:59:00")]
)
def test_parse_time(value: str, expected: str) -> None:
    assert validation.parse_time(value) == expected


@pytest.mark.parametrize("value", ["24:00", "9", "9:7", "noon"])
def test_parse_time_rejects(value: str) -> None:
    with pytest.raises(ValidationError):
        validation.parse_time(value)


@pytest.mark.parametrize(
    ("name", "start", "end"),
    [
        ("today", date(2026, 1, 14), date(2026, 1, 14)),
        ("yesterday", date(2026, 1, 13), date(2026, 1, 13)),
        ("week", date(2026, 1, 12), date(2026, 1, 18)),
        ("last-week", date(2026, 1, 5), date(2026, 1, 11)),
        ("month", date(2026, 1, 1), date(2026, 1, 31)),
        ("last-month", date(2025, 12, 1), date(2025, 12, 31)),
    ],
)
def test_period_range(name: str, start: date, end: date) -> None:
    rng = validation.period_range(name, today=TODAY)
    assert (rng.start, rng.end) == (start, end)


def test_period_range_february_and_unknown() -> None:
    rng = validation.period_range("month", today=date(2028, 2, 10))
    assert rng.end == date(2028, 2, 29)
    with pytest.raises(ValidationError):
        validation.period_range("decade", today=TODAY)


def test_resolve_range() -> None:
    rng = validation.resolve_range(None, "2026-01-01", "2026-01-03", today=TODAY)
    assert len(rng.days()) == 3
    assert validation.resolve_range(None, "monday", None, today=TODAY).end == TODAY
    assert validation.resolve_range(None, None, "2026-01-10", today=TODAY).start == date(
        2026, 1, 10
    )
    assert validation.resolve_range(None, None, None, default="today", today=TODAY).start == TODAY
    with pytest.raises(ValidationError):
        validation.resolve_range("week", "2026-01-01", None, today=TODAY)
    with pytest.raises(ValidationError):
        validation.resolve_range(None, "2026-01-05", "2026-01-01", today=TODAY)
    with pytest.raises(ValidationError):
        validation.resolve_range(None, "2024-01-01", "2026-01-01", today=TODAY)


def test_identifiers() -> None:
    assert validation.issue_key("proj-12") == "PROJ-12"
    assert validation.project_key("abc") == "ABC"
    assert validation.account_id("557058:abc-123") == "557058:abc-123"
    assert validation.worklog_id(" 42 ") == "42"
    assert validation.is_issue_id("10001")
    for bad in ["PROJ", "PROJ-0", "-1", "PROJ-1/../x", "1PROJ-1"]:
        with pytest.raises(ValidationError):
            validation.issue_key(bad)
    with pytest.raises(ValidationError):
        validation.project_key("A B")
    with pytest.raises(ValidationError):
        validation.account_id("../me")
    with pytest.raises(ValidationError):
        validation.worklog_id("12a")


def test_attribute_and_description() -> None:
    assert validation.attribute("_Role_=Developer") == ("_Role_", "Developer")
    assert validation.attribute("k= v=w ") == ("k", "v=w")
    for bad in ["noequals", "bad key=x", "k=\x00"]:
        with pytest.raises(ValidationError):
            validation.attribute(bad)
    assert validation.description("line1\nline2") == "line1\nline2"
    with pytest.raises(ValidationError):
        validation.description("bell\x07")
    with pytest.raises(ValidationError):
        validation.description("x" * 10_001)
