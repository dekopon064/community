"""원천 날짜 파싱. 실패해도 항목·실행을 실패시키지 않는다."""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple

from ingest.models import ParseStatus

RAW_MAX_LEN = 64
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_KNOWN_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


class ParsedSourceTime(NamedTuple):
    value: str | None
    raw: str | None
    status: ParseStatus


def sanitize_raw_date(raw: object) -> str | None:
    if raw is None:
        return None
    text = _CONTROL_RE.sub("", str(raw)).strip()
    if not text:
        return None
    return text[:RAW_MAX_LEN]


def parse_source_datetime(raw: object) -> ParsedSourceTime:
    sanitized = sanitize_raw_date(raw)
    if sanitized is None:
        return ParsedSourceTime(None, None, "missing")
    for fmt in _KNOWN_FORMATS:
        try:
            parsed = datetime.strptime(sanitized, fmt)
        except ValueError:
            continue
        iso = parsed.isoformat()
        return ParsedSourceTime(iso, sanitized, "ok")
    return ParsedSourceTime(None, sanitized, "unparsed")
