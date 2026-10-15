"""Pure Seoul evidence readers. No I/O, current-row edits or eligibility guesses."""
from __future__ import annotations

import re
from datetime import date

VENUE_LABELS = ('진행장소', '체험장소', '운영장소', '개최장소', '개최지', '교육장소', '장소')
ACTIVITY_LABELS = ('목적', '주요활동', '활동내용', '주요내용', '교육내용', '프로그램내용', '내용')
_BULLET = re.compile(r'^[\s□■○ㅇ❐•●▪▶▷※*·\-✅☑✔✓◆◇🔸🔹\ufe0f]+')
_COLUMN = re.compile(r'^(?:제목\s*[/·]\s*소요시간|활동\s*내용|시간|요일|장\s*소|내\s*용)$')
_UNCLEAR = re.compile(r'미정|불명확|확인\s*필요|추후\s*안내')
_VENUE_UNCERTAIN = re.compile(r'아님|아닌|미사용|변경|사용하지\s*않|진행하지\s*않')
_VENUE = re.compile(r'공원|교육실|학습센터|체험관|배움관|미술관|박물관|도서관|공방|전시실|교육장|숲길|치유의\s*숲|\d+\s*(?:층|번지)|(?:로|길)\s*\d+')
_BOILERPLATE = re.compile(r'개인정보[^\n]*(?:동의|이용\s*안내)|사진\s*사용|촬영\s*동의|공통\s*이용안내|필수\s*준수사항|^\s*(?:\d+[.)]\s*)?주의사항|^\s*[\[<*○■\s]*(?:시설\s*안내|일반\s*관람\s*안내)')
_FACILITY = re.compile(r'^\s*[\[<*○■\s]*(?:시설\s*안내|일반\s*관람\s*안내)')
_CONTEXT_LABELS = VENUE_LABELS + ('대상', '참여대상', '참가대상', '일정', '기간', '신청방법', '문의', '준비물',
                                '관람시간', '시설안내', '운영기간', '진행기간', '접수기간', '신청기간', '모집기간', '비용', '참가비', '오시는길')


def _clean(line: str) -> str:
    line = _BULLET.sub('', line.strip())
    return re.sub(r'^(?:\d{1,2}[.)]\s*|[①-⑳]\s*)', '', line)


def label_match(line: str, labels) -> tuple[str, str] | None:
    line = _clean(line)
    for label in labels:
        pattern = r'\s*'.join(map(re.escape, label.replace(' ', '')))
        m = re.match(r'^\[?' + pattern + r'(?=[\]\s:：|]|$)[\]\s]*[:：|]?\s*(.*)$', line)
        if m:
            return label, m[1].strip(' |')
    return None


def label_values(text: str, labels) -> tuple[str, ...]:
    lines = text.splitlines()
    values = []
    venue_role = any(label.replace(' ', '') in VENUE_LABELS for label in labels)
    for i, raw in enumerate(lines):
        # A table with multiple columns must be read by cell position below.
        cells = [s.strip() for s in raw.strip().strip('|').split('|')]
        if '|' in raw and len(cells) != 2:
            continue
        line = raw.strip().strip('| ')
        matched = label_match(line, labels)
        if not matched:
            continue
        value = matched[1]
        if not value and i + 1 < len(lines):
            following = lines[i + 1].strip()
            # Do not associate a flattened table's next row with its last header.
            header_neighbors = any(_COLUMN.fullmatch(_clean(s)) for s in lines[max(0, i-2):i])
            if header_neighbors or label_match(following, VENUE_LABELS + ACTIVITY_LABELS):
                continue
            if venue_role and not _VENUE.search(following):
                continue
            value = following
        if value and not _UNCLEAR.search(value) and '|' not in value:
            if venue_role and (re.search(r'오시는\s*길|출구|하차|집결|정류장|기관\s*주소', value) or _VENUE_UNCERTAIN.search(value)):
                continue
            values.append(value)
    return tuple(dict.fromkeys(values))


def activity_locations(text: str, tables=()) -> tuple[str, ...]:
    values = list(label_values(text, VENUE_LABELS))
    nested = {n for table in tables or () if isinstance(table, list) for row in table if isinstance(row, list)
              for cell in row if isinstance(cell, dict) for n in cell.get('nested_tables', ())}
    for table_index, table in enumerate(tables or ()):
        if table_index in nested:
            continue
        if not isinstance(table, list) or len(table) < 2 or not table[0]:
            continue
        if any(not isinstance(row, list) or len(row) != len(table[0]) for row in table):
            continue
        if any(not isinstance(c, dict) or c.get('rowspan', 1) != 1 or c.get('colspan', 1) != 1 or c.get('nested_tables')
               for row in table for c in row):
            continue
        indexes = [i for i, c in enumerate(table[0]) if re.sub(r'\s+', '', c.get('text', '')) in VENUE_LABELS]
        if len(indexes) != 1:
            continue
        for row in table[1:]:
            value = row[indexes[0]].get('text', '').strip()
            if value and not _UNCLEAR.search(value) and not _VENUE_UNCERTAIN.search(value) and not re.search(r'집결|오시는\s*길|정류장|기관\s*주소', value):
                values.append(value)
    return tuple(dict.fromkeys(values))


def matching_place(place: str, locations) -> bool:
    """Only explicit facility identity, never fuzzy aliases/provider area alone."""
    normalize = lambda s: re.sub(r'\s+', '', s)
    p = normalize(place)
    if len(p) < 3 or p in {'센터', '교육장', '교육실', '학습센터', '관리사무소', '체험관'}:
        return False
    return bool(locations) and all(normalize(v).startswith(p) for v in locations)


def activity_text(text: str) -> str:
    """Main activity sections; do not promote a facility/privacy common guide."""
    lines = text.splitlines()
    cutoff = next((i for i, line in enumerate(lines) if _BOILERPLATE.search(line) and not _FACILITY.search(line)), len(lines))
    lines = lines[:cutoff]
    sections = []
    active = False
    for line in lines:
        matched = label_match(line, ACTIVITY_LABELS)
        if matched:
            active = True
            sections.append(matched[1])
        elif active and (label_match(line, _CONTEXT_LABELS)
                         or re.match(r'^\s*\[', line)):
            active = False
        elif active:
            sections.append(line)
    if sections:
        return '\n'.join(sections).strip()
    facility_start = next((i for i, line in enumerate(lines) if _FACILITY.search(line)), len(lines))
    return '\n'.join(line for line in lines[:facility_start] if not label_match(line, _CONTEXT_LABELS)).strip()


NATURE_ACTIVITY = re.compile(
    r'생태\s*(?:놀이|교육|관찰|탐방|활동)|숲\s*(?:치유|명상|해설|체험|탐방)|'
    r'(?:열매|곤충|나비|풀씨|풀벌레|자연|숲)(?:를|와|의|에)?[^\n.]{0,20}(?:찾|관찰|알아|이야기|성장|여행|탐구|놀이|운동회|음악회)|'
    r'(?:키링|액자|공예품)\s*만들기|(?:전시|나비정원)\s*(?:해설|관람)')


def uncertain_activity(text: str) -> bool:
    return bool(re.search(r'불명확|확인\s*필요|미정|(?:놀이|교육|체험|치유|교류|관람)\s*(?:은|는|이|가|을|를)?\s*(?:진행|실시|운영|제공)?\s*(?:아님|아닌|제외|하지\s*않|없음|불가|중단)', text))


def nature_topic(text: str) -> bool:
    main = activity_text(text)
    if uncertain_activity(main):
        return False
    # Do not turn a list of facility amenities into a program purpose.
    if re.search(r'시설\s*(?:이용|소개|안내)|일반\s*관람\s*안내', main) and not label_values(main, ('프로그램내용', '주요활동')):
        return False
    return bool(NATURE_ACTIVITY.search(main))


_LEFT = r'(?P<y>20\d{2})\s*[.년/-]\s*(?P<m>\d{1,2})\s*[.월/-]\s*(?P<d>\d{1,2})\s*(?:일|\.)?\s*(?:\(\s*(?P<w>[월화수목금토일])(?:요일)?\s*\))?'
_RIGHT = r'(?:(?P<ey>20\d{2})\s*[.년/-]\s*)?(?:(?P<em>\d{1,2})\s*[.월/-]\s*)?(?P<ed>\d{1,2})\s*(?:일|\.)?\s*(?:\(\s*(?P<ew>[월화수목금토일])(?:요일)?\s*\))?'
_RANGE = re.compile(_LEFT + r'\s*(?:[~～〜–—-]|부터)\s*' + _RIGHT + r'(?!\d)')


def period_days(statement: str) -> tuple[tuple[str, str] | None, str | None]:
    """End year/month inherit ONLY from the same explicit range's left endpoint."""
    matches = list(_RANGE.finditer(statement))
    if len(matches) != 1:
        return None, 'body_period_needs_confirmation'
    m = matches[0]
    remainder = statement[:m.start()] + statement[m.end():]
    if re.search(r'20\d{2}\s*[.년/-]|\d{1,2}\s*월\s*\d{1,2}|(?<!\d)\d{1,2}[./-]\d{1,2}', remainder):
        return None, 'body_period_needs_confirmation'
    try:
        a = date(int(m['y']), int(m['m']), int(m['d']))
        b = date(int(m['ey'] or m['y']), int(m['em'] or m['m']), int(m['ed']))
    except ValueError:
        return None, 'invalid_body_date'
    if any(weekday and '월화수목금토일'[value.weekday()] != weekday for value, weekday in ((a,m['w']),(b,m['ew']))):
        return None, 'date_weekday_conflict'
    if b < a:
        return None, 'period_order_conflict'
    return (a.isoformat(), b.isoformat()), None
