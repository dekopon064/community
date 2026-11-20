"""Validate date/time session tables against current Seoul schedule evidence.

An explicit date list with one trailing clock range shares that range, not a
continuous period or an inferred recurrence. Other mixed prose is not expanded.
"""
import re

from ingest.ai_errors import ValidationError, validation_location
from ingest.body_markdown import read_body, inline_text
from ingest.myseoul_content import schedule_lines, _operation_date_bounds
from ingest.translation_validation import _dates_and_times
from ingest.seoul_condition_layout import session_slot

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


def numbered_day_source(view, records):
    """One explicit date heading immediately followed by its numbered slots."""
    bounds = _operation_date_bounds(view)
    if len(bounds) != 1 or bounds[0][0] != bounds[0][1] or len(records) < 2:
        return None
    day = bounds[0][0]
    heading = re.fullmatch(r'(?:✅\s*)?(?:운영\s*)?일시\s*[:：]\s*(?:(\d{4})년\s*)?'
                           r'(\d+)월\s*(\d+)일\s*\(([월화수목금토일])(?:요일)?\)\s*'
                           r'(?:[*※]?\s*((?:약\s*)?\d+\s*분)\s*소요)?', records[0])
    if (not heading or (int(heading[1] or day.year), int(heading[2]), int(heading[3])) !=
            (day.year, day.month, day.day) or heading[4] != '월화수목금토일'[day.weekday()]):
        return None
    source = [line.strip() for line in view['description'].splitlines() if line.strip()]
    if source.count(records[0]) != 1:
        return None
    start = source.index(records[0])
    if source[start:start+len(records)] != records:
        return None
    slots = [session_slot(v) for v in records[1:]]
    if not all(slots) or len({s[0] for s in slots}) != len(slots):
        return None
    return day, heading[5], slots


def matches_numbered_table(table, source):
    if not source:
        return False
    day, _, slots = source
    headers = tuple(inline_text(h) for h in table.headers)
    if (len(headers) != 3 or '회차' not in headers or '시간' not in headers
            or not {'일자','날짜','일시','일정','운영일','교육일','수업일'} & set(headers)):
        return False
    daycol = next(i for i, name in enumerate(headers) if name not in ('회차','시간'))
    actual = []
    for row in table.rows:
        text = inline_text(row[daycol])
        if not re.fullmatch(_DATE + _DAY, text):
            return False
        if _dates_and_times(text, known_years=frozenset({day.year})) != [('date',day.year,day.month,day.day)]:
            return False
        weekday = re.search(r'[（(]\s*([월화수목금토일])', text)
        if weekday and weekday[1] != '월화수목금토일'[day.weekday()]:
            return False
        ordinal = re.fullmatch(r'(?:제\s*)?(\d+)\s*회차', inline_text(row[headers.index('회차')]))
        if not ordinal:
            return False
        actual.append(session_slot(f'({ordinal[1]}회차) ' + row[headers.index('시간')]))
    return actual == slots


def dated_slot_evidence(view):
    records = schedule_lines(view)
    source = numbered_day_source(view, records)
    if not source:
        return view
    day, _, slots = source
    prefix = f'{day.year}년 {day.month}월 {day.day}일({"월화수목금토일"[day.weekday()]})'
    dated = [f'{prefix} {ordinal}회차 {start//60:02}:{start%60:02}~{end//60:02}:{end%60:02}'
             for ordinal, start, end in slots]
    return {**view, 'session_evidence': [records[0], *dated]}


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
    for index, table in enumerate(read_body(content).tables, 1):
        headers = [inline_text(h).strip() for h in table.headers]
        dates = [i for i,h in enumerate(headers) if h in {'날짜','일자','일시','일정','수업일','교육일'}]
        clocks = [i for i,h in enumerate(headers) if h in {'시간','진행 시간','수업 시간'}]
        # Weekly matrices/fee tables and ordinary date prose keep their own
        # existing validators. This is only an explicit date+time session table.
        if not dates or not clocks:
            continue
        if len(dates)!=1 or len(clocks)!=1:
            raise ValidationError('calendar_table_columns', 'invalid_shape', location={'table': index},
                                  expected=(1, 1), actual=(len(dates), len(clocks)))
        for row_index, row in enumerate(table.rows, 1):
            with validation_location(table=index, row=row_index, column=dates[0]+1):
                date_values = _dates_and_times(inline_text(row[dates[0]]),known_years=years)
            with validation_location(table=index, row=row_index, column=clocks[0]+1):
                time_values = _dates_and_times(inline_text(row[clocks[0]]),known_years=years)
            if len(date_values)!=1 or date_values[0][0]!='date' or any(v[0]!='time' for v in time_values) or len(time_values)!=2:
                raise ValidationError('calendar_table_row', 'invalid_shape', location={'table': index, 'row': row_index},
                                      expected=(1, 2), actual=(len(date_values), len(time_values)))
            actual = date_values[0][1:]
            matches = [times for day,times in records if day==actual or day[0] is None and day[1:]==actual[1:]]
            if not matches:
                raise ValidationError('calendar_session_date', 'unsupported',
                                      location={'table': index, 'row': row_index, 'column': dates[0]+1},
                                      expected=[('date', *day) for day, _ in records], actual=date_values)
            if not any(tuple(time_values)==times for times in matches):
                raise ValidationError('calendar_session_clock', 'mismatch',
                                      location={'table': index, 'row': row_index, 'column': clocks[0]+1},
                                      expected=matches, actual=time_values)
            # Ordered evidence preserves real overnight/midnight sessions too;
            # no blanket start<end rule or recovery from a global number bag.
