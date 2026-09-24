"""Current-revision application deadline facts.

Unconfirmed is the absence of a fact, not a stored kind. Dates are accepted
only in the formats listed below. Missing years are not inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

APPLICATION_DEADLINE_UNKNOWN = "application_deadline_unknown"
DEADLINE_KIND_FIXED = "fixed"
DEADLINE_KIND_NONE = "none"
DEADLINE_KIND_CLOSED = "closed"
DEADLINE_KINDS = frozenset(
    {DEADLINE_KIND_FIXED, DEADLINE_KIND_NONE, DEADLINE_KIND_CLOSED}
)

POLICY_CODE_FIXED = "0057001"
POLICY_CODE_NONE = "0057002"
POLICY_CODE_CLOSED = "0057003"

_DATE_PATTERNS = (
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})(\d{2})(\d{2})"),
    re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
)
_TIME_AFTER = re.compile(r"^\s*\d{1,2}\s*:\s*\d{2}")
_AFTER_DATE = re.compile(r"^(?:까지|입니다|이다|임|임\.|\.|\)|,|，|。|\s|$)")
_RANGE_SPLIT = re.compile(r"[~∼～]|부터")
_CLOSED_SENTENCES = frozenset(
    {
        "접수가 마감되었습니다",
        "신청이 마감되었습니다",
        "모집이 종료되었습니다",
        "접수 종료",
    }
)
_NONE_SENTENCES = frozenset(
    {
        "상시 모집 중",
        "상시 접수 중",
        "신청은 상시 가능",
    }
)
_TRAILING_SENTENCE_MARK = re.compile(r"[.!?。！？]+$")
_PERIOD_CHUNK = re.compile(
    r"(?:신청|접수|모집)\s*기간\s*[:：]?\s*([^。\n]{0,80})"
)
_DEADLINE_DATE = re.compile(
    r"(?:신청|접수|모집)\s*마감일?\s*(?:은|는|이|:|：)?\s*"
)
_UNTIL_DATE = re.compile(r"(?:신청|접수|모집)\s*(?:은|는)?\s*")


@dataclass(frozen=True)
class ApplicationDeadline:
    kind: str
    on: str | None

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "on": self.on}


def parse_policy_application_deadline(
    code: object, aply_ymd: object
) -> ApplicationDeadline | None:
    """Map aplyPrdSeCd and aplyYmd. Business-period fields are not inputs."""
    normalized = str(code or "").strip()
    if normalized == POLICY_CODE_NONE:
        return ApplicationDeadline(DEADLINE_KIND_NONE, None)
    if normalized == POLICY_CODE_CLOSED:
        return ApplicationDeadline(DEADLINE_KIND_CLOSED, None)
    if normalized != POLICY_CODE_FIXED:
        return None
    parsed = _parse_aply_ymd_end(aply_ymd)
    if parsed is None:
        return None
    return ApplicationDeadline(DEADLINE_KIND_FIXED, parsed.isoformat())


def parse_content_application_deadline(text: object) -> ApplicationDeadline | None:
    """Confirm a deadline only from an explicit application phrase in the body."""
    raw = str(text or "")
    plain = " ".join(raw.split())
    if not plain:
        return None
    dates, ambiguous = _content_deadline_dates(plain)
    if len(dates) == 1 and not ambiguous:
        return ApplicationDeadline(DEADLINE_KIND_FIXED, dates[0])
    if dates or ambiguous:
        return None
    statuses = _allowlisted_statuses(raw)
    if len(statuses) != 1:
        return None
    return ApplicationDeadline(next(iter(statuses)), None)


def _allowlisted_statuses(text: str) -> set[str]:
    found: set[str] = set()
    for line in re.split(r"\r\n|\n|\r", text):
        for piece in re.split(r"(?<=[.!?。！？])", line):
            sentence = _TRAILING_SENTENCE_MARK.sub("", piece.strip())
            if sentence in _CLOSED_SENTENCES:
                found.add(DEADLINE_KIND_CLOSED)
            elif sentence in _NONE_SENTENCES:
                found.add(DEADLINE_KIND_NONE)
    return found


def _parse_aply_ymd_end(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or _TIME_AFTER.search(text):
        return None
    parts = _RANGE_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2:
        end = parts[1].split("까지", 1)[0].strip()
        if not re.search(r"\d{4}", end):
            return None
        return _leading_date(end)
    return _leading_date(text.split("까지", 1)[0].strip())


def _content_deadline_dates(text: str) -> tuple[list[str], bool]:
    found: list[str] = []
    ambiguous = False
    for match in _PERIOD_CHUNK.finditer(text):
        chunk = match.group(1)
        if _RANGE_SPLIT.search(chunk) is None:
            continue
        end = _RANGE_SPLIT.split(chunk, maxsplit=1)[1]
        end = end.split("까지", 1)[0]
        if not re.search(r"\d{4}", end):
            ambiguous = True
            continue
        parsed = _leading_date(end)
        if parsed is None:
            ambiguous = True
        else:
            found.append(parsed.isoformat())
    for match in _DEADLINE_DATE.finditer(text):
        window = text[match.end() : match.end() + 48]
        parsed = _date_in_window(window)
        if parsed is not None:
            found.append(parsed.isoformat())
        elif re.search(r"\d", window):
            ambiguous = True
    for match in _UNTIL_DATE.finditer(text):
        window = text[match.end() : match.end() + 48]
        if window.startswith("기간") or window.startswith("마감"):
            continue
        if "까지" not in window:
            continue
        parsed = _date_in_window(window.split("까지", 1)[0])
        if parsed is not None:
            found.append(parsed.isoformat())
        elif re.search(r"\d", window):
            ambiguous = True
    dates = list(dict.fromkeys(found))
    if len(dates) > 1:
        ambiguous = True
    return dates, ambiguous


def _date_in_window(window: str) -> date | None:
    if _RANGE_SPLIT.search(window):
        end = _RANGE_SPLIT.split(window, maxsplit=1)[1]
        if not re.search(r"\d{4}", end):
            return None
        return _leading_date(end.split("까지", 1)[0])
    return _leading_date(window)


def _leading_date(text: str) -> date | None:
    candidate = text.strip().lstrip(":：").strip()
    if not candidate:
        return None
    for pattern in _DATE_PATTERNS:
        match = pattern.match(candidate)
        if match is None:
            continue
        rest = candidate[match.end() :]
        if _TIME_AFTER.match(rest):
            return None
        if rest and _AFTER_DATE.match(rest) is None:
            continue
        parsed = _valid_date(*match.groups())
        if parsed is not None:
            return parsed
    return None


def _valid_date(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None
