"""Human-confirmed, revision-scoped category and period rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

USER_CATEGORIES = frozenset({"policy", "program", "event", "youth_space", "living"})
APPLICATION_CATEGORIES = frozenset({"policy", "program"})
USER_CATEGORY_UNCONFIRMED = "user_category_unconfirmed"
EVENT_PERIOD_UNKNOWN = "event_period_unknown"


@dataclass(frozen=True)
class EventPeriod:
    start_on: str
    end_on: str


def validated_event_period(start_on: str | None, end_on: str | None) -> EventPeriod:
    if start_on is None or end_on is None:
        raise ValueError("invalid_event_period")
    try:
        start = date.fromisoformat(start_on)
        end = date.fromisoformat(end_on)
    except ValueError:
        raise ValueError("invalid_event_period") from None
    if start.isoformat() != start_on or end.isoformat() != end_on or start > end:
        raise ValueError("invalid_event_period")
    return EventPeriod(start.isoformat(), end.isoformat())
