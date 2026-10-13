"""Small generated-body subset, never a repair or general Markdown interpreter.

Stored bodies stay untouched. Comparison text retains table column/row labels;
callers still validate authoritative facts and translated values by role.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from ingest.ai_errors import AiJobError

_LIST = re.compile(r'^( *)(?:([-+*])\s+|(\d+)[.)]\s+)(\S.*)$')
_LINK = re.compile(r'(?<!!)\[([^\]\n]+)\]\((https?://[^\s]+?)\)')
_STRONG = re.compile(r'(?<!\\)\*\*([^\n]+?)\*\*')
_SEPARATOR = re.compile(r':?-{3,}:?')
_LABELS = re.compile(
    r'^(신청\s*기간|진행\s*기간|운영\s*기간|개최\s*기간|신청\s*마감|진행 일정|'
    r'집결 안내|(?:합격자|선정자|결과)\s*발표|장소|비용|모집 인원|진행 방식|'
    r'신청 링크|신청 방법|참가 조건|대상|명시 조건|거주 조건(?: 근거)?|'
    r'참가 대상 근거|개최지 근거|신청 주체|비용 구분|분류|접수 상태)\s*[:：]\s*(\S.*)$')


def inline_text(text: str) -> str:
    """Only supported inline delimiters; don't normalize opaque URL characters."""
    text = _LINK.sub(lambda m: m[1] + ' ' + m[2], text)
    text = re.sub(r'<(https?://[^\s<>]+)>', r'\1', text)
    text = _STRONG.sub(r'\1', text)
    text = re.sub(r'(?<![\\*])\*([^*\n]+)\*(?!\*)', r'\1', text)
    return re.sub(r'\\([|*\[\]\\])', r'\1', text)


def strong_spans(text: str) -> list[str]:
    return [inline_text(m[1]) for m in _STRONG.finditer(text)]


def _cells(line: str) -> tuple[str, ...]:
    # Split only unescaped GFM cell delimiters; an escaped pipe is content.
    text = line.strip()
    if text.startswith('|'):
        text = text[1:]
    if text.endswith('|') and not text.endswith('\\|'):
        text = text[:-1]
    return tuple(cell.strip() for cell in re.split(r'(?<!\\)\|', text))


def is_weekday_matrix(headers: tuple[str, ...]) -> bool:
    """Only explicit time-by-weekday columns allow unoccupied session cells.

    Recognize both sides of the translation contract; don't infer weekdays
    from prose or allow blank dates/activities in unrelated session tables.
    """
    labels = tuple(inline_text(h).strip() for h in headers)
    return len(labels) >= 2 and (
        bool(re.fullmatch(r'시간(?:\s*[/·]\s*요일)?', labels[0]))
        and all(re.fullmatch(r'[월화수목금토일](?:요일)?', h) for h in labels[1:])
        or bool(re.fullmatch(r'(?:時間|時刻)(?:\s*[/・·]\s*曜日)?', labels[0]))
        and all(re.fullmatch(r'[月火水木金土日](?:曜日)?', h) for h in labels[1:]))


@dataclass(frozen=True)
class Table:
    section: int
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    markdown: str = ''


@dataclass(frozen=True)
class ListItem:
    section: int
    indent: int
    number: int | None
    text: str


@dataclass(frozen=True)
class Body:
    text: str
    tables: tuple[Table, ...]
    items: tuple[ListItem, ...]


def read_body(content: str) -> Body:
    """Read generated paragraphs, inline emphasis/links, lists and GFM tables.

    No source fetching, HTML, code execution or AST-based facts inference.
    Plain legacy bodies use the same comparison representation.
    """
    if re.search(r'(?m)^\s*(?:`{3,}|~{3,}|#{1,6}\s)|`[^`\n]+`|</?[A-Za-z][^>]*>|!\[', content):
        raise AiJobError('ai_schema_error')
    if re.search(r'\d[\d,.]*\*\*(?:원|명|세|회|시|분|년|월|일|ウォン|名|歳|回|時|分|年|月|日)', content):
        raise AiJobError('ai_schema_error')
    lines = content.splitlines()
    tables, items, plain = [], [], []
    section = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r'^\s*\[[^\]\n]+\](?:\s|$)', line):
            section += 1
        if index + 1 < len(lines) and '|' in line:
            separators = _cells(lines[index + 1])
            if separators and all(_SEPARATOR.fullmatch(c) for c in separators):
                start = index
                headers = _cells(line)
                if len(headers) < 2 or len(headers) != len(separators) or any(not h for h in headers):
                    raise AiJobError('ai_schema_error')
                weekday_matrix = is_weekday_matrix(headers)
                index += 2
                rows = []
                while index < len(lines) and '|' in lines[index] and lines[index].strip():
                    row = _cells(lines[index])
                    # A present empty session cell differs from a missing
                    # delimiter/column. Retain it, including adjacent/trailing
                    # empties; the required row clock and all widths stay strict.
                    if (len(row) != len(headers) or not row[0]
                            or (not weekday_matrix and any(not c for c in row))):
                        raise AiJobError('ai_schema_error')
                    rows.append(row)
                    values = [inline_text(c) for c in row]
                    # First-cell row label + every column label are retained.
                    plain.append('; '.join([values[0] + ': ' + ' '.join(values[1:]),
                        *(inline_text(h) + ': ' + v for h, v in zip(headers, values))]))
                    index += 1
                if not rows:
                    raise AiJobError('ai_schema_error')
                tables.append(Table(section, headers, tuple(rows), '\n'.join(lines[start:index])))
                continue
        if line.lstrip().startswith('|'):
            raise AiJobError('ai_schema_error')
        match = _LIST.match(line)
        if match:
            value = inline_text(match[4])
            items.append(ListItem(section, len(match[1]), int(match[3]) if match[3] else None, value))
            plain.append(value)
        else:
            plain.append(inline_text(line))
        index += 1
    return Body('\n'.join(plain), tuple(tables), tuple(items))


def comparison_text(content: str) -> str:
    return read_body(content).text


def schedule_tables(content: str) -> tuple[Table, ...]:
    return tuple(table for table in read_body(content).tables if any(
        re.fullmatch(r'회차|수업일|교육일', inline_text(h)) for h in table.headers))


def schedule_table_lines(content: str) -> list[str]:
    """Only explicitly labeled session tables, not every date in a table."""
    result = []
    for table in schedule_tables(content):
        for row in table.rows:
            result.append('회차: ' + ' '.join(inline_text(cell) for cell in row))
    return result


def format_reviewed_block(text: str) -> str:
    """Style explicit reviewed labels, without interpreting values or tables."""
    output = []
    for line in text.splitlines():
        match = _LABELS.fullmatch(line)
        output.append(f'- **{match[1]}:** {match[2]}' if match else line)
    return '\n'.join(output)


def require_plain_summary(text: str) -> None:
    if (read_body(text).tables or read_body(text).items or strong_spans(text)
            or _LINK.search(text) or re.search(r'(?m)^\s*#{1,6}\s|`[^`]+`', text)):
        raise AiJobError('ai_schema_error')
