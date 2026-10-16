"""Pure Seoul evidence readers. No I/O, current-row edits or eligibility guesses."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

VENUE_LABELS = ('진행장소', '체험장소', '운영장소', '개최장소', '개최지', '교육장소', '활동장소', '수업장소', '장소', '위치')
ACTIVITY_LABELS = ('프로그램목적', '프로그램소개', '세부프로그램내용', '프로그램주요내용',
                   '프로그램내용', '체험소개', '운영내용', '목적', '주요활동', '활동내용', '주요내용', '교육내용', '내용')
_BULLET = re.compile(r'^[\s□■○ㅇ❍〇◎❐•⦁●▪▶▷►▹※*·\-✅☑✔✓◆◇🔸🔹📍♠♣\ufe0f]+')
_COLUMN = re.compile(r'^(?:제목\s*[/·]\s*소요시간|활동\s*내용|시간|요일|장\s*소|내\s*용|장소\s*(?:및|[/·])\s*시간)\]?$')
_UNCLEAR = re.compile(r'미정|불명확|확인\s*필요|추후\s*안내')
_VENUE_UNCERTAIN = re.compile(r'아님|아닌|미사용|변경\s*(?:전|후|예정|중)|사용하지\s*않|진행하지\s*않')
_VENUE = re.compile(r'공원|교육실|센터|체험관|배움관|미술관|박물관|도서관|공방|전시실|교육장|강의실|식물원|숲길|치유의\s*숲|체험\s*부스|현장\s*부스|\d+\s*(?:층|번지)|(?:로|길)\s*\d+')
_BOILERPLATE = re.compile(r'개인정보[^\n]*(?:동의|이용\s*안내)|사진\s*사용|촬영\s*동의|공통\s*이용안내|필수\s*준수사항|^\s*(?:\d+[.)]\s*)?주의사항|^\s*[\[<*○■\s]*(?:시설\s*안내|일반\s*관람\s*안내)')
_FACILITY = re.compile(r'^\s*[\[<*○■\s]*(?:시설\s*안내|일반\s*관람\s*안내)')
_CONTEXT_LABELS = VENUE_LABELS + ('대상', '참여대상', '참가대상', '일정', '기간', '신청방법', '문의', '준비물',
                                '관람시간', '시설안내', '운영기간', '진행기간', '접수기간', '신청기간', '모집기간', '비용', '참가비', '오시는길')


def _clean(line: str) -> str:
    line = line.strip()
    # Decorative symbols vary by publisher; their Unicode role is structural.
    # Keep brackets, letters, digits and every character inside the value.
    while line and (line[0].isspace() or unicodedata.category(line[0]) in {'So', 'Sm', 'Sk', 'Cf', 'Mn'}):
        line = line[1:]
    line = _BULLET.sub('', line)
    return re.sub(r'^(?:\d{1,2}[.)]\s*|[①-⑳]\s*)', '', line)


def label_match(line: str, labels) -> tuple[str, str] | None:
    line = _clean(line)
    if _COLUMN.fullmatch(line.strip('[] ')) and not any(line.strip('[] ') == x for x in labels):
        return None
    for label in labels:
        pattern = r'\s*'.join(map(re.escape, label.replace(' ', '')))
        m = re.match(r'^\[?' + pattern + r'(?=[\]\s:：|]|$)[\]\s]*[:：|]?\s*(.*)$', line)
        if m:
            return label, m[1].strip(' |')
    return None


def _venue_lines(text: str) -> list[str]:
    """Keep line positions, but exclude facility/directions sections as venues."""
    lines = []
    guide = False
    for line in text.splitlines():
        heading = _clean(line).strip('[<>【】] ')
        if _FACILITY.search(heading) or re.match(r'^(?:주차(?:\s*및\s*위치)?|오시는\s*길|위치)\s*안내', heading):
            guide = True
        else:
            section = label_match(line, ACTIVITY_LABELS)
            if section and section[0] not in {'내용', '목적', '운영내용'}:
                guide = False
        lines.append('' if guide else line)
    return lines


def label_values(text: str, labels) -> tuple[str, ...]:
    values = []
    venue_role = any(label.replace(' ', '') in VENUE_LABELS for label in labels)
    lines = _venue_lines(text) if venue_role else text.splitlines()
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
        if venue_role and matched[0] == '위치' and not activity_text(text):
            continue
        if not value and i + 1 < len(lines):
            following = _clean(lines[i + 1]).lstrip(':： ')
            # Do not associate a flattened table's next row with its last header.
            header_neighbors = any(_COLUMN.fullmatch(_clean(s)) for s in lines[max(0, i-2):i])
            if header_neighbors or label_match(following, VENUE_LABELS + ACTIVITY_LABELS):
                continue
            if venue_role and not _VENUE.search(following):
                continue
            value = following
        if value and not _UNCLEAR.search(value) and '|' not in value:
            if venue_role:
                if re.search(r'오시는\s*길|하차|집결|정류장|기관\s*주소', value) or _VENUE_UNCERTAIN.search(value):
                    continue
                if '출구' in value and not re.search(r'(?:야외|현장|체험)\s*(?:현장\s*|체험\s*)?부스', value):
                    continue
            values.append(value)
    return tuple(dict.fromkeys(values))


def activity_locations(text: str, tables=()) -> tuple[str, ...]:
    values = list(label_values(text, VENUE_LABELS))
    # An explicit venue performing an activity is also a venue role. A
    # provider name by itself, a meeting point or a contact address is not.
    for line in _venue_lines(text):
        m = re.match(r'^([가-힣A-Za-z0-9()·\s-]{1,80}?(?:체험장|공원|박물관|전시관|교육장|공방|센터|식물원))에서(?:는)?\s+(.+)$', _clean(line))
        if (m and re.search(r'(?:목공\s*체험|전시\s*해설|체험을\s*운영|교육을\s*진행)', m[2])
                and not re.search(r'집결|기관\s*주소|진행하지|운영하지|아님|아닌|미정', line)):
            values.append(m[1].strip())
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
    def normalize(s):
        return re.sub(r'[\s()×]+', '', _clean(s))
    p = normalize(place)
    if len(p) < 3 or p in {'센터', '교육장', '교육실', '학습센터', '관리사무소', '체험관'}:
        return False
    return bool(locations) and all(normalize(v).startswith(p) for v in locations)


def activity_text(text: str) -> str:
    """Main activity sections; do not promote a facility/privacy common guide."""
    lines = [part for line in text.splitlines() for part in
             re.split(r'\s*[/|]\s*(?=(?:내용|활동내용)\s*[:：])',line)]
    sections = []
    active = False
    saw_activity = False
    blocked = False
    for index, line in enumerate(lines):
        if _BOILERPLATE.search(line):
            blocked = True
            active = False
            continue
        matched = label_match(line, ACTIVITY_LABELS)
        # A flattened table's empty "내용" column header must not discard the
        # introductory program description or attach a different column's cells.
        neighbors = [s for s in lines[max(0,index-4):index+5] if s.strip() and s != line]
        if matched and not matched[1] and any(_COLUMN.fullmatch(_clean(s)) for s in neighbors):
            active = False
            continue
        if matched:
            # A clearly labelled program section can follow a common guide.
            # Generic facility "내용/목적" cannot reopen it.
            if blocked and matched[0] in {'내용', '목적', '운영내용'}:
                continue
            blocked = False
            active = True
            saw_activity = True
            sections.append(matched[1])
        elif active and (label_match(line, _CONTEXT_LABELS)
                         or re.match(r'^\s*\[', line)):
            active = False
        elif active:
            sections.append(line)
        elif not blocked and not saw_activity and not label_match(line, _CONTEXT_LABELS):
            # Introductory activity evidence remains part of this program,
            # even when a later curriculum section is short or flattened.
            sections.append(line)
    return '\n'.join(sections).strip()


def physical_activity(text: str) -> bool:
    """Physical activity evidence, independent of whether its district is known."""
    main = activity_text(text)
    return any(re.search(r'도보\s*(?:관광|탐방|여행|답사)|트레킹|노르딕워킹|현장\s*(?:대면\s*수업|견학|투어)|(?:공원|숲길|도성|정원|수목원)[^\n.]{0,40}(?:걷|걸|거닐|산책|탐방|돌아보|방문)', line)
               and not re.search(r'진행하지|아님|불가|검색|다른\s*프로그램|취소|준비|미취학|주의사항|온라인|비대면|영상', line)
               for line in main.splitlines())


def venue_filter(text: str, provider_fields=None, tables=()):
    """All explicit venues must be provable; never reuse an unbound old quote."""
    from ingest.content_filters import DISTRICTS, _location
    venues = activity_locations(text, tables)
    raw = provider_fields or {}
    resolved = []
    nationwide = False
    for venue in venues:
        if re.search(r'[<>\x00-\x1f]|부산|대구|대전|제주|강원|충청|전라|경상', venue):
            return None
        explicit = _location(venue)
        if explicit and explicit['scope'] == 'nationwide':
            nationwide = True
            continue
        if explicit and all(v['district'] for v in explicit['venues']):
            resolved.extend(explicit['venues']); continue
        # A district appearing in the actual venue is different from an
        # institution district supplied only by the provider.
        pairs = [(province,district) for province, choices in DISTRICTS.items() for district in choices
                 if re.search(r'(?<![가-힣])'+re.escape(district)+r'(?![가-힣])', venue)]
        if len(pairs) == 1 and raw.get('AREANM') == pairs[0][1]:
            province,district = pairs[0]
            resolved.append(dict(province=province,district=district,facility='',address=venue)); continue
        # A district directly qualifying a named actual venue is explicit
        # evidence (e.g. "영등포구보건소"), unlike the provider area alone.
        # Short directional districts do not identify a city; the selectable
        # inventory is not a national (or historical) uniqueness registry.
        attached = [(province,district) for province, choices in DISTRICTS.items() for district in choices
                    if len(district) >= 3 and raw.get('AREANM') == district
                    and re.match(re.escape(district) + r'(?:청|보건소|교육장|문화센터|체험장)(?:\b|[가-힣0-9\s])', _clean(venue))]
        if len(attached) == 1:
            province,district = attached[0]
            resolved.append(dict(province=province,district=district,facility='',address=venue)); continue
        place, area = raw.get('PLACENM'), raw.get('AREANM')
        pairs = [(province,area) for province, choices in DISTRICTS.items() if area in choices]
        if isinstance(place,str) and matching_place(place,(venue,)) and len(pairs)==1:
            province,district = pairs[0]
            resolved.append(dict(province=province,district=district,facility=place,address='')); continue
        return None
    if nationwide:
        return {'scope':'nationwide','venues':[]} if not resolved else None
    unique = []
    for venue in resolved:
        if venue not in unique: unique.append(venue)
    return {'scope':'specific','venues':unique} if unique else None


def activity_topic(text: str, base: str | None = None) -> str | None:
    """Seoul-only semantic families, after activity/boilerplate role selection."""
    main = activity_text(text)
    if uncertain_activity(main) or re.search(r'주거\s*정책|지원금|시설\s*(?:이용|소개|안내)|일반\s*관람\s*안내', main):
        return None
    found = {base} if base else set()
    # Recount generic competing purposes even when the base classifier returned
    # no single choice. An additional vocabulary match cannot erase ambiguity.
    if re.search(r'(?:문화|공예|미술|음악|창작|취미|요리)\s*(?:체험|활동|교육|수업|강좌)|(?:그림|공예품)\s*만들기',main):
        found.add('culture_experience')
    if nature_topic(text): found.add('culture_experience')
    # An explicit arts lesson describes an activity, not just a course name.
    # No provider title or facility inventory is used as the positive proof.
    if re.search(r'(?:음악|성악|가곡|무용|댄스|악기|그림|드로잉|사진|공예)[^\n.]{0,45}(?:배우|배워|실습|창작|직접\s*(?:만들|제작))', main):
        found.add('culture_experience')
    patterns = {
        'culture_experience': r'목공\s*체험|전통\s*공예\s*체험|공예\s*(?:활동|워크숍|체험|수업)|(?:자연물|만다라|향기\s*주머니|압화\s*액자|단풍\s*액자|새\s*밥그릇|나무\s*반지|나무\s*시계|벽선반|벽걸이\s*책꽂이|수납꽂이|우드\s*미니\s*스피커|미니\s*우드\s*스피커|책갈피|아로마\s*롤온|계란꾸러미|냄비받침|디폼블럭|자개\s*소품|양말목)[^\n]{0,24}(?:만들|제작)|가드닝을\s*통해|꽃꽂이\s*하기|화분\s*심기|정원\s*실습|허브비누만들기|가옥\s*해설사와\s*함께하는[^\n]{0,40}도슨트|전시\s*해설\s*(?:프로그램|운영|예약)|전시해설\s*프로그램|박물관[^\n]{0,20}전시해설|주얼리를\s*전공한[^\n]{0,30}클래스를\s*진행',
        'daily_safety': r'심폐소생술[^\n]{0,30}(?:교육|실습)|(?:구조|응급처치)[^\n]{0,30}(?:교육|실습)|소방안전\s*교육',
        'language_learning': r'(?:챗GPT|클로드)[^\n]{0,50}실습|코딩\s*없이\s*업무\s*자동화[^\n]{0,20}과정',
        'community_exchange': r'(?:주민|지역|이웃)\s*(?:교류|만남|활동)|교류\s*(?:활동|모임)',
    }
    found.update(key for key,pattern in patterns.items() if re.search(pattern,main))
    return next(iter(found)) if len(found)==1 else None


NATURE_ACTIVITY = re.compile(
    r'생태\s*(?:놀이|교육|관찰|탐방|활동|해설)|숲\s*(?:치유|명상|해설|체험|탐방)|'
    r'산림\s*(?:치유|교육|체험)|(?:역사\s*문화|문화\s*관광|문화유산)\s*(?:도보\s*)?(?:해설|탐방|답사)|'
    r'(?:열매|곤충|나비|풀씨|풀벌레|자연|숲)(?:를|와|의|에)?[^\n.]{0,20}(?:찾|관찰|알아|이야기|성장|여행|탐구|놀이|운동회|음악회)|'
    r'(?:키링|액자|공예품)\s*만들기|(?:전시|나비정원)\s*(?:해설|관람)')


def uncertain_activity(text: str) -> bool:
    for line in text.splitlines():
        # Conditional cancellation is not a denial of the advertised activity.
        # Remove only that conditional predicate, never other denials on its
        # line. A cancellation condition cannot hide an unrelated uncertainty.
        line = re.sub(r'(?:(?:신청|예약|참여)\s*인원[^\n.;]{0,35}(?:미달|이하|미만)|기상\s*악화)[^\n.;]{0,35}?(?:교육|체험|활동)?\s*(?:진행|운영)?\s*(?:불가|중단|취소)', '', line)
        if re.search(r'불명확|확인\s*필요|미정|(?:놀이|교육|체험|치유|교류|관람|해설|탐방|실습|창작|제작)\s*(?:은|는|이|가|을|를)?\s*(?:진행|실시|운영|제공)?\s*(?:아님|아닌|제외|하지\s*않|없음|불가|중단)|배우지\s*않',line):
            return True
    return False


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


def period_proof(statement: str, role: str):
    """Dates plus explicitly stated clocks. No clock is inferred from midnight."""
    one = re.fullmatch(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})\.?',statement)
    if one and role == 'SVCOPN':
        try: day = date(*map(int,one.groups())).isoformat()
        except ValueError: return None,None,'invalid_body_date'
        return (day,day),(None,None),None
    hours = re.fullmatch(r'(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2})시\s*~\s*(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2})시',statement)
    if hours:
        y,m,d,h,em,ed,eh = map(int,hours.groups())
        if h>23 or eh>23: return None,None,'invalid_body_date'
        days,issue = period_days(f'{y}.{m}.{d}~{y}.{em}.{ed}')
        return days,(f'{h:02d}:00:00',f'{eh:02d}:00:00'),issue
    days,issue = period_days(statement)
    match = _RANGE.match(statement)
    if issue or not match: return None,None,issue or 'body_period_needs_confirmation'
    suffix = statement[match.end():].strip()
    clock = re.fullmatch(r'([0-9]{1,2}):([0-5][0-9])',suffix) if suffix else None
    if suffix and (not clock or int(clock[1])>23):return None,None,'body_period_needs_confirmation'
    return days,(None,f'{int(clock[1]):02d}:{clock[2]}:00' if clock else None),None
