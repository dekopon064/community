"""Approved Korean-to-Japanese region names. The YAML file is the only copy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ingest.ai_errors import AiJobError

_GLOSSARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "ingest-inputs"
    / "region_ja_glossary.v1.yaml"
)
_ENTRY_RE = re.compile(
    r"^-\s*\{parent_ko: (null|[^,}]+), ko: ([^,]+), level: ([^,]+), "
    r"ja: ([^,]+), status: ([^}]+)\}$"
)
_HANGUL_RE = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]")
_YEN_MARKS = ("円", "￥", "¥")


@dataclass(frozen=True)
class RegionEntry:
    parent_ko: str | None
    ko: str
    level: str
    ja: str
    status: str


def glossary_path() -> Path:
    return _GLOSSARY_PATH


@lru_cache(maxsize=1)
def load_region_entries() -> tuple[RegionEntry, ...]:
    text = _GLOSSARY_PATH.read_text(encoding="utf-8")
    entries: list[RegionEntry] = []
    seen: set[tuple[str | None, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- {"):
            continue
        match = _ENTRY_RE.fullmatch(line)
        if match is None:
            raise ValueError("region_glossary_entry_unparsed")
        parent_raw, ko, level, ja, status = match.groups()
        parent_ko = None if parent_raw == "null" else parent_raw.strip()
        entry = RegionEntry(
            parent_ko=parent_ko,
            ko=ko.strip(),
            level=level.strip(),
            ja=ja.strip(),
            status=status.strip(),
        )
        key = (entry.parent_ko, entry.ko)
        if key in seen:
            raise ValueError("region_glossary_duplicate")
        seen.add(key)
        entries.append(entry)
    if not entries:
        raise ValueError("region_glossary_empty")
    return tuple(entries)


def approved_ja(ko: str, parent_ko: str | None = None) -> str:
    matches = [
        entry
        for entry in load_region_entries()
        if entry.ko == ko and (parent_ko is None or entry.parent_ko == parent_ko)
    ]
    if len(matches) != 1:
        raise KeyError(ko)
    return matches[0].ja


def glossary_prompt_block() -> str:
    lines = [
        "Approved region glossary. Use these Japanese forms exactly:",
    ]
    for entry in load_region_entries():
        parent = "" if entry.parent_ko is None else f"{entry.parent_ko}/"
        lines.append(f"{parent}{entry.ko} → {entry.ja}")
    return "\n".join(lines)


def regions_in_text(text: str) -> tuple[RegionEntry, ...]:
    """Longest non-overlapping Korean names present in text."""
    claimed = [False] * len(text)
    found: list[RegionEntry] = []
    seen: set[tuple[str | None, str]] = set()
    entries = sorted(load_region_entries(), key=lambda entry: len(entry.ko), reverse=True)
    for entry in entries:
        start = 0
        while True:
            index = text.find(entry.ko, start)
            if index < 0:
                break
            end = index + len(entry.ko)
            if not any(claimed[index:end]):
                for cursor in range(index, end):
                    claimed[cursor] = True
                key = (entry.parent_ko, entry.ko)
                if key not in seen:
                    seen.add(key)
                    found.append(entry)
            start = index + 1
    return tuple(found)


def validate_japanese_output(title_ja: str, content_ja: str, korean_source: str) -> None:
    if not isinstance(title_ja, str) or not title_ja.strip():
        raise AiJobError("ai_schema_error")
    if not isinstance(content_ja, str) or not content_ja.strip():
        raise AiJobError("ai_schema_error")
    combined = f"{title_ja}\n{content_ja}"
    if _HANGUL_RE.search(combined) is not None:
        raise AiJobError("ai_schema_error")
    if any(mark in combined for mark in _YEN_MARKS):
        raise AiJobError("ai_schema_error")
    for entry in regions_in_text(korean_source):
        if entry.ja not in combined:
            raise AiJobError("ai_schema_error")
