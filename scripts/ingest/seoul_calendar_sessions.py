"""Validate date/time session tables against current Seoul schedule evidence.

An explicit date list with one trailing clock range shares that range, not a
continuous period or an inferred recurrence. Other mixed prose is not expanded.
"""
import re

from ingest.ai_errors import AiJobError
from ingest.body_markdown import read_body, inline_text
from ingest.myseoul_content import schedule_lines, _operation_date_bounds
from ingest.translation_validation import _dates_and_times

_DATE = (r"(?:\d{4}-\d{2}-\d{2}|(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일|"
         r"(?:(?:\d{4}|['’]\d{2})\s*\.\s*)?\d{1,2}\s*\.\s*\d{1,2}\.?)")
_DAY = r'(?:\s*[（(]\s*[월화수목금토일](?:요일)?\s*[）)])?'
_CLOCK = r'(?:오전|오후)?\s*\d{1,2}(?::\d{2}(?::\d{2})?|\s*시(?!간)(?:\s*\d{1,2}\s*분)?)'
_SHARED = re.compile(rf'^(?P<dates>{_DATE}{_DAY}(?:\s*[/,·、・]\s*{_DATE}{_DAY})+)'
                     rf'\s*[,;:]?\s*(?P<clocks>{_CLOCK}\s*[~～〜–—-]\s*{_CLOCK})'
                     r'(?P<note>\s+.*)?\s*$')


def session_text(line):
    text = re.sub(r'^[^\w가-힣]+', '', inline_text(line)).strip()
    return re.sub(r'^[ㅇ]?\s*(?:운영|진행|교육|수업)?\s*(?:일시|일정)\s*[:：]\s*', '', text)


def record_calendar_sessions(line, *, years=frozenset()):
    """Same date/ordered-clock evidence for validation and display coverage."""
    text = session_text(line)
    match = _SHARED.fullmatch(text)
    if match and not _dates_and_times(match['note'] or '',known_years=years):
        # Time-free conditions don't change the explicit shared clocks. They
        # remain source text for public display; never deduplicate this note.
        # Another date/clock in the tail needs its own association, not sharing.
        clocks = tuple(v for v in _dates_and_times(match['clocks']) if v[0]=='time')
        return [(v[1:],clocks) for v in _dates_and_times(match['dates'],known_years=years) if v[0]=='date']
    records = []; day = None; clocks = []
    # Each date opens its own ordered interval. Repeated identical clocks on
    # another date are not additional clocks belonging to this date's session.
    for value in _dates_and_times(text,known_years=years):
        if value[0]=='date':
            if day is not None:records.append((day,tuple(clocks)))
            day=value[1:];clocks=[]
        elif day is not None:clocks.append(value)
    if day is not None:records.append((day,tuple(clocks)))
    return records


def calendar_session_records(view):
    bounds = _operation_date_bounds(view)
    years = frozenset(y for start,end in bounds for y in range(start.year,end.year+1))
    records = []
    for line in schedule_lines(view):
        # Strip an explicit source schedule label, never a title/invitation.
        records += record_calendar_sessions(line, years=years)
    return records


def validate_calendar_sessions(content, view):
    bounds = _operation_date_bounds(view)
    years = frozenset(y for start,end in bounds for y in range(start.year,end.year+1))
    records = calendar_session_records(view)
    for table in read_body(content).tables:
        headers = [inline_text(h).strip() for h in table.headers]
        dates = [i for i,h in enumerate(headers) if h in {'날짜','일자','일시','일정','수업일','교육일'}]
        clocks = [i for i,h in enumerate(headers) if h in {'시간','진행 시간','수업 시간'}]
        # Weekly matrices/fee tables and ordinary date prose keep their own
        # existing validators. This is only an explicit date+time session table.
        if not dates or not clocks:
            continue
        if len(dates)!=1 or len(clocks)!=1:
            raise AiJobError('ai_schema_error')
        for row in table.rows:
            date_values = _dates_and_times(inline_text(row[dates[0]]),known_years=years)
            time_values = _dates_and_times(inline_text(row[clocks[0]]),known_years=years)
            if len(date_values)!=1 or date_values[0][0]!='date' or any(v[0]!='time' for v in time_values) or len(time_values)!=2:
                raise AiJobError('ai_schema_error')
            actual = date_values[0][1:]
            matches = [times for day,times in records if day==actual or day[0] is None and day[1:]==actual[1:]]
            if not matches or not any(tuple(time_values)==times for times in matches):
                raise AiJobError('ai_schema_error')
            # Ordered evidence preserves real overnight/midnight sessions too;
            # no blanket start<end rule or recovery from a global number bag.
