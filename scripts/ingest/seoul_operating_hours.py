"""Bounded facility-hour evidence from current Seoul reviewed description.

Opening hours are not sessions. No observations fallback, calendar expansion,
facts mutation or broad permission to use any clock found in source prose.
"""
import re

from ingest.ai_errors import AiJobError
from ingest.body_markdown import inline_text
from ingest.translation_validation import _dates_and_times

_FACILITY = r'(?:센터|시설|도서관|박물관|미술관|전시관|공원)'
_CLOCK = r'(?:오전|오후)?\s*\d{1,2}(?::\d{2}(?::\d{2})?|\s*시(?!간)(?:\s*\d{1,2}\s*분)?)'
_RANGE = re.compile(rf'({_CLOCK})\s*(?:~|～|〜|–|—|-|부터)\s*({_CLOCK})(?:까지)?')


def _plain(text):
    return re.sub(r'^[\s\d.)▹▶○●■□*+\-]+', '', inline_text(text)).strip()


def _facility_hours(text):
    return bool(re.search(_FACILITY + r'\s*(?:의\s*)?(?:운영|이용|개관)\s*시간', text)
                or re.search(_FACILITY + r'(?:은|는)\s*' + _CLOCK, text)
                and re.search(r'(?:까지\s*)?(?:운영|개관)(?:합니다|됩니다|한다|함)', text))


def _ranges(text):
    result = []
    for match in _RANGE.finditer(text):
        clocks = [v for v in _dates_and_times(match[0]) if v[0] == 'time']
        if len(clocks) != 2:
            raise AiJobError('ai_schema_error')
        result.append(tuple(tuple(v[1:]) for v in clocks))
    return result


def facility_hours_evidence(description):
    """Only named facility opening-hour lines, not bare '시간' or sessions."""
    records = []
    for line in description.splitlines():
        text = _plain(line)
        if (len(text) > 1500 or not _facility_hours(text)
                or re.search(r'접수|신청|관람|회차|수업|운영하지|운영\s*안\s*함', text)):
            continue
        ranges = _ranges(text)
        # Mixed dates or extra clocks cannot establish a simple opening window.
        values = _dates_and_times(text)
        if len(ranges) == 1 and len([v for v in values if v[0] == 'time']) == 2 and not any(v[0] == 'date' for v in values):
            records.append({'role': 'facility_opening', 'evidence': line.strip(),
                            'clocks': [list(clock) for clock in ranges[0]]})
    return records


def validate_facility_hours_clause(line, facts):
    """Return True only for proven facility clocks in their original role.

    The caller must still validate dates, weekdays, counts and durations. A
    matching clock is never proof of a daily session or an agreed appointment.
    """
    text = _plain(line)
    records = facts.get('facility_hours_evidence', [])
    ranges = _ranges(text)
    if not ranges:
        return False
    # A receipt/viewing window needs its own explicit current-description
    # evidence; an identical facility clock is not interchangeable authority.
    for role in (r'(?:신청|접수)\s*(?:시간|은|는)', r'(?:일반\s*)?관람\s*(?:시간|은|는)'):
        if records and re.search(role, text):
            own = {r for source in facts.get('description','').splitlines()
                   if re.search(role, source) for r in _ranges(source)}
            if any(r not in own for r in ranges):
                raise AiJobError('ai_schema_error')
            return True
    if not _facility_hours(text):
        # Explicit fixed session claims must not borrow opening/receipt clocks,
        # even when the older generic checker sees no '일정/회차' keyword.
        if records and re.search(r'(?:프로그램|체험|수업|행사).*(?:진행|운영)|매일.*(?:진행|운영)', text):
            from ingest.myseoul_content import schedule_lines
            allowed = {r for value in schedule_lines(facts) for r in _ranges(value)}
            if any(r not in allowed for r in ranges):
                raise AiJobError('ai_schema_error')
        return False
    expected = {tuple(tuple(clock) for clock in record['clocks']) for record in records}
    if (len(ranges) != 1 or ranges[0] not in expected
            or re.search(r'접수|신청|관람|회차|매일.*(?:프로그램|체험|수업)|'
                         r'(?:프로그램|체험|수업|행사).*(?:진행|운영)\s*(?:합니다|됩니다)', text)):
        raise AiJobError('ai_schema_error')
    if re.search(r'협의|조율', text) and not re.search(
            r'(?:일정|시간)[^\n.。]{0,100}(?:협의|조율)|(?:협의|조율)[^\n.。]{0,100}(?:일정|시간)',
            facts.get('description', '')):
        raise AiJobError('ai_schema_error')
    return True
