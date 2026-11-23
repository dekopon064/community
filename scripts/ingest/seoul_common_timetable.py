"""Compact only a dated, source-proven set of identical check-in and tour slots."""
import re
from dataclasses import dataclass
from datetime import date

from ingest.body_markdown import inline_text, read_body
from ingest.myseoul_content import _operation_date_bounds, _unique_operation_year, schedule_lines
from ingest.seoul_fact_roles import CLOCK


DAY = r'(?:\d{4}년\s*)?\d{1,2}월\s*\d{1,2}일\s*\([월화수목금토일]\)'
DAYS = rf'{DAY}(?:\s*[,·/]\s*{DAY})*'
HOUR = r'(?:[01]?\d|2[0-3])시(?:\s*[0-5]?\d분)?'
OVERVIEW = re.compile(rf'({DAY})\s*[:：]\s*({HOUR}(?:\s*[/,]\s*{HOUR})*)'
                      r'(?:\s*\(총\s*(\d+)\s*회차\))?')
RANGE = rf'({CLOCK})\s*[~～–-]\s*({CLOCK})'
SLOT = re.compile(rf'(\d+)회차\s*[-–—:]\s*{RANGE}\s*\(\s*접수\s*시간\s*[:：]\s*{RANGE}\s*\)')
DETAIL = re.compile(r'(?:공통\s+)?회차별\s*운영\s*시간(?:\s*\((?:전체|전)\s*운영일\s*공통\))?')
NOTE = re.compile(r'(?:해당\s*)?회차\s*(?:시작\s*\(출발\)|출발)\s*후에는\s*'
                  r'(?:참여가\s*(?:불가능합니다|불가합니다|불가)|참여할\s*수\s*없습니다)[.]?')
# A dated override can also occur outside the timetable, e.g. in a course note.
QUALIFIED = re.compile(r'\d+\s*월\s*\d+\s*일|(?<!\d)(?:1[0-2]|0?[1-9])[./-](?:3[01]|[12]\d|0?[1-9])(?!\d)|'
                       r'\d+일(?:에|만|은)|공휴일|평일|주말|[월화수목금토일]요일|첫\s*날|마지막\s*(?:날|주)|둘째|첫째|셋째|'
                       r'(?:두|세|첫)\s*번째\s*(?:날|주)|\d+\s*주\s*차|'
                       r'특정\s*(?:일|회차)|(?:회차|운영일|날짜)\s*(?:별로|마다)\s*(?:상이|다[르름])')
NEXT_SECTION = re.compile(r'(?:장소\s*및\s*운영\s*코스(?:\s*\(.*\))?|참가\s*안내|준비\s*및\s*유의사항|\[\s*문의\s*\])')


def _plain(line):
    return inline_text(line).strip().lstrip('-▪※📅⏰ ').strip()


def _day_label(raw, bounds):
    match = re.fullmatch(r'(?:(\d{4})년\s*)?(\d+)월\s*(\d+)일\s*\(([월화수목금토일])\)', raw)
    month, day = int(match[2]), int(match[3])
    year = _unique_operation_year(month, day, bounds)
    if not year or (match[1] and int(match[1]) != year) or '월화수목금토일'[date(year, month, day).weekday()] != match[4]:
        return None
    return f'{month}월 {day}일({match[4]})'


@dataclass
class CommonSchedule:
    year: int
    dates: list[str]
    slots: list[tuple[str, ...]]
    source_lines: set[str]
    note: str

    def date_label(self, text):
        if not re.fullmatch(DAY, text):
            return None
        text = re.sub(rf'^{self.year}년\s*', '', text)
        return re.sub(r'(?<!\d)0(?=\d[월일])', '', text).replace(' (', '(')

    def table(self):
        lines = ['| 회차 | 당일 접수 시간 | 진행 시간 |', '| --- | --- | --- |']
        for number, start, end, arrival, close in self.slots:
            lines.append(f'| {number}회차 | {arrival}~{close} | {start}~{end} |')
        return '\n'.join(lines)


def source_schedule(view, conditions=()):
    description = view['description']
    if '회차별' not in description or '접수' not in description:
        return None
    # Operator-confirmed schedule qualifications can exist outside the prose.
    # Do not replace those with a shared timetable derived from prose alone.
    if any(_plain(v) not in description and (QUALIFIED.search(v) or re.search(r'회차|접수\s*시간|출발', v))
           for v in conditions):
        return None
    bounds = _operation_date_bounds(view)
    if len(bounds) != 1 or bounds[0][0].year != bounds[0][1].year:
        return None
    overview, slots, day_notes, declared, covered = {}, {}, {}, [], set()
    detail = False
    group = ()
    note = ''
    for raw in description.splitlines():
        line = _plain(raw)
        if not line:
            continue
        if DETAIL.fullmatch(line):
            if detail or slots:
                return None
            detail = True
            group = tuple(overview) if '공통' in line else ()
            continue
        if NEXT_SECTION.fullmatch(line):
            detail = False
        starts = OVERVIEW.fullmatch(line)
        if starts and not detail:
            day = _day_label(starts[1], bounds)
            if not day or day in overview:
                return None
            clocks = re.findall(r'(\d+)시(?:\s*(\d+)분)?', starts[2])
            if starts[3] and int(starts[3]) != len(clocks):
                return None
            overview[day] = [f'{int(h):02}:{int(m or 0):02}' for h, m in clocks]
            covered.add(line)
            continue
        dates = re.sub(r'^운영\s*(?:일시|일)\s*[:：]\s*', '', line)
        if re.fullmatch(DAYS, dates):
            labels = [_day_label(d, bounds) for d in re.findall(DAY, dates)]
            if None in labels or len(set(labels)) != len(labels):
                return None
            if detail:
                if any(day in slots for day in labels):
                    return None
                group = labels
            elif dates != line:
                declared.extend(labels)
            else:
                return None
            covered.add(line)
            continue
        row = SLOT.fullmatch(line)
        if detail and row and group:
            for day in group:
                slots.setdefault(day, []).append(row.groups())
            covered.add(line)
            continue
        if NOTE.fullmatch(line):
            if detail:
                if not group:
                    return None
                for day in group:
                    day_notes[day] = line
            else:
                note = line
            covered.add(line)
            continue
        if detail or row or QUALIFIED.search(line):
            return None
    if len(overview) < 2 or overview.keys() != slots.keys() or (declared and declared != list(overview)):
        return None
    common = slots[next(iter(overview))]
    if len({row[0] for row in common}) != len(common):
        return None
    if any(not (arrival.zfill(5) <= close.zfill(5) <= start.zfill(5) < end.zfill(5))
           for _, start, end, arrival, close in common):
        return None
    if day_notes:
        if day_notes.keys() != overview.keys() or len(set(day_notes.values())) != 1:
            return None
        note = next(iter(day_notes.values()))
    for day, starts in overview.items():
        if slots[day] != common or starts != [row[1].zfill(5) for row in common]:
            return None
    return CommonSchedule(bounds[0][0].year, list(overview), common, covered, note)


def _covered_table(table, source):
    # Remove an existing common table only after comparing every cell by role.
    aliases = {'일자': 'day', '날짜': 'day', '운영일': 'day',
               '회차': 'slot', '접수 시간': 'checkin', '당일 접수 시간': 'checkin',
               '도착 접수 시간': 'checkin', '진행 시간': 'tour', '투어 시간': 'tour', '투어 진행 시간': 'tour'}
    roles = [aliases.get(inline_text(h).strip()) for h in table.headers]
    if set(roles) not in ({'checkin','slot','tour'}, {'day','checkin','slot','tour'}) or len(set(roles)) != len(roles):
        return False
    actual = []
    for cells in table.rows:
        values = dict(zip(roles, cells))
        number = re.fullmatch(r'(\d+)회차', inline_text(values['slot']).strip())
        tour = re.fullmatch(RANGE, inline_text(values['tour']).strip())
        arrival = re.fullmatch(RANGE, inline_text(values['checkin']).strip())
        if not (number and tour and arrival):
            return False
        actual_row = (number[1], *tour.groups(), *arrival.groups())
        if 'day' in values:
            label = source.date_label(inline_text(values['day']).strip())
            actual_row = (label, *actual_row)
        actual.append(actual_row)
    expected = [(day, *s) for day in source.dates for s in source.slots] if 'day' in roles else source.slots
    return actual == expected


_SECTION = re.compile(r'(?ms)^\[일정 안내\]\n(.*?)(?=^\[(?:주요 내용|신청 방법)\]|\Z)')


def timetable_validation_input(summary, view, source):
    if not source:
        return summary, view
    section = _SECTION.search(summary)
    tables = read_body(section[1]).tables if section else ()
    if not tables or not all(_covered_table(t, source) for t in tables):
        return summary, view
    # All cells, dates and time roles match the source. The existing ordinal
    # validator expects one row per session number.
    checked = section[1]
    for table in tables:
        checked = checked.replace(table.markdown, source.table(), 1)
    records = [f'{n}회차 {start}~{end} (접수시간: {arrival}~{close})'
               for n, start, end, arrival, close in source.slots]
    return (summary[:section.start(1)] + checked + summary[section.end(1):],
            {**view, 'session_evidence': schedule_lines(view) + records})


def common_timetable(body, source):
    if not source:
        return body
    dates, covered, note = source.dates, source.source_lines, source.note
    match = _SECTION.search(body)
    if not match:
        return body
    section = match[1]
    for table in read_body(section).tables:
        if not _covered_table(table, source):
            return body
        section = section.replace(table.markdown, '', 1)
    remaining = []
    for line in section.splitlines():
        text = re.sub(r'^진행 일정\s*[:：]\s*', '', _plain(line))
        date_list = re.fullmatch(rf'운영일\s*[:：]\s*({DAYS})', text)
        if (text in covered or _plain(line) == '진행 일정:'
                or (date_list and [source.date_label(d) for d in re.findall(DAY, date_list[1])] == dates)
                or (note and NOTE.fullmatch(text))):
            continue
        if text.startswith(('신청기간:', '진행기간:')):
            remaining.append(line)
            continue
        if QUALIFIED.search(text) or re.search(r'\d+\s*(?:회차|시(?!간)|:\d{2})', text):
            return body
        remaining.append(line)
    block = ['**운영일:** ' + ', '.join(dates), '', source.table()]
    if note:
        block.extend(['', note])
    return body[:match.start(1)] + '\n'.join(remaining).strip() + '\n\n' + '\n'.join(block) + '\n\n' + body[match.end(1):]
