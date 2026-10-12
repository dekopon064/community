"""Seoul-only presentation cleanup AFTER fact validation, never stored edits."""
from __future__ import annotations
import re
from ingest.body_markdown import inline_text, read_body
from ingest.myseoul_ai_support import schedule_values
from ingest.myseoul_content import schedule_block, schedule_lines
from ingest.translation_validation import _entry

_SECTION = re.compile(r'(?ms)(^[ \t]*\[일정 안내\][ \t]*)(.*?)(?=^[ \t]*\[|\Z)')
_DATE = r'(?:\d{4}-\d{2}-\d{2}|(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일)'
_CLOCK = r'(?:\d{1,2}:[0-5]\d(?::[0-5]\d)?|\d{1,2}\s*시(?!간)(?:\s*[0-5]?\d\s*분)?)'
_POINT = rf'{_DATE}(?:[T \t]+{_CLOCK})?(?:Z|[+-]\d{{2}}:?\d{{2}})?'
_RANGE = re.compile(rf'{_POINT}\s*(?:~|～|〜|–|—|-)\s*{_POINT}')
_APPLICATION = r'신청\s*기간|접수\s*기간|접수|신청'
_OPERATION = r'진행\s*기간|운영\s*기간|개최\s*기간|운영'


def _plain(line: str) -> str:
    return re.sub(r'^\s*[-+*]\s+', '', inline_text(line)).strip()


def normalize_period_labels(content: str) -> str:
    """Expose aliases to the existing role validator BEFORE removing anything."""
    def section(match):
        lines=[]
        for line in match[2].splitlines():
            plain=_plain(line)
            alias=re.fullmatch(rf'({_APPLICATION}|{_OPERATION})\s*[:：]\s*(.+)',plain)
            if alias and re.match(_DATE,alias[2]):
                role='신청기간' if re.fullmatch(_APPLICATION,alias[1]) else '진행기간'
                line=role+': '+alias[2]
            lines.append(line)
        return match[1]+'\n'+'\n'.join(lines).strip()+'\n\n'
    return _SECTION.sub(section,content)


def _table_rows(section: str) -> list[str]:
    result=[]
    for table in read_body(section).tables:
        headers={inline_text(h) for h in table.headers}
        if (headers & {'날짜','일자','수업일','교육일','회차'}
                and headers & {'시간','일시','오전','오후'}):
            result += [' '.join(inline_text(cell) for cell in row) for row in table.rows]
    return result


def _pure_session(record: str) -> bool:
    # Do not remove meeting instructions, activities, per-session conditions or
    # duration/count notes just because a table has the same numeric values.
    text=_plain(record)
    if not schedule_values(text)['dates']:
        return False
    text=re.sub(_DATE,'',text)
    text=re.sub(_CLOCK,'',text)
    text=re.sub(r'[（(]\s*[월화수목금토일](?:요일)?\s*[）)]|오전|오후','',text)
    return not text.strip(' \t/,·、・;；~～〜–—-')


def clean_schedule_display(content: str, sections: dict, view: dict) -> tuple[str,dict]:
    """Keep verified session tables and only source records they fully cover.

    Unknown/mixed prose stays. Values are already validated by role/year/date;
    table coverage is per record, not a global numeric-set comparison.
    """
    supplied=sections
    sections=dict(sections)
    match=_SECTION.search(content)
    if not match:
        return content,sections
    original=match[2]
    rows=[schedule_values(row) for row in _table_rows(original)]
    records=schedule_lines(view)
    covered=[]
    for record in records:
        values=schedule_values(record)
        if _pure_session(record) and any(values['dates']==row['dates'] and
                all(values[key].issubset(row[key]) for key in ('years','times','weekdays','counts'))
                for row in rows):
            covered.append(record)
    remaining=[record for record in records if record not in covered]
    def remove_block(text):
        block=schedule_block(records)
        return text.replace(block,schedule_block(remaining),1) if block else text
    canonical=remove_block(sections['[일정 안내]'])
    # Exact source/generated table equality only. Do not deduplicate different
    # activities/headers/cell layouts or replace one by reconstructed prose.
    tables=read_body(original).tables
    for table in read_body(canonical).tables:
        if any(table.headers==other.headers and table.rows==other.rows for other in tables):
            canonical=canonical.replace(table.markdown,'',1)
    sections['[일정 안내]']=canonical.strip()
    roles={role for role,labels in (
        ('신청기간',r'신청\s*기간'),('진행기간',r'진행\s*기간|운영\s*기간|개최\s*기간'))
        if _entry(supplied['[일정 안내]'],labels) is not None}
    lines=[]
    for line in remove_block(original).splitlines():
        plain=_plain(line)
        period=re.fullmatch(r'(신청기간|진행기간)\s*[:：]\s*(.+)',plain)
        if period and period[1] in roles and _RANGE.fullmatch(period[2]):
            continue
        # Internal control metadata is not a public instruction. Keep ordinary
        # Korean-time guidance, opaque URLs/identifiers and mixed source prose.
        if re.fullmatch(r'(?:시간\s*(?:기준|대)|시간대)\s*[:：]\s*Asia/Seoul\.?',plain):
            continue
        if re.fullmatch(r'모든\s*시간은\s*한국시간\s*[（(]Asia/Seoul[）)]입니다\.',plain):
            line='모든 시간은 한국시간입니다.'
        lines.append(line)
    replacement=match[1]+'\n'+'\n'.join(lines).strip()+'\n\n'
    content=content[:match.start()]+replacement+content[match.end():]
    return content,sections
