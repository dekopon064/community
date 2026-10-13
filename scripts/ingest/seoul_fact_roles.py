"""Read-only public roles for legacy Seoul keyword observations.

The stored conditions array is NOT a typed eligibility list. Split only explicit
labels/structures; unknown or mixed restrictions remain intact. No DB schema,
calendar expansion, source lookup or generated replacement facts.
"""
from dataclasses import dataclass
import re
from ingest.ai_errors import AiJobError
from ingest.body_markdown import inline_text, read_body

ORDINAL = r'(?:제\s*)?\d+\s*회차'
WEEKDAY = r'[월화수목금토일](?:요일)?'
CLOCK = r'(?:[01]?\d|2[0-3]):[0-5]\d'
EMPTY_CELL = frozenset({'', '—', '–', '-', '없음'})
CAPACITY = r'(?:참가\s*인원|모집\s*인원|인원|정원)'
SCHEDULE = r'(?:해설|운영|진행|수업|교육)\s*(?:시간|일시|일정)(?:\s*안내)?'
RESTRICTION = r'필수|의무|불가|금지|제한|전용|한정|보호자|동반|거주|국적|비자|증빙|제출|취소|환불|선착순'


def plain(text):
    return re.sub(r'^[\s▹▶○●■□*+\-]+', '', inline_text(text)).strip()


def key(text):
    return re.sub(r'\s+', '', inline_text(text))


@dataclass(frozen=True)
class WeeklySchedule:
    headers: tuple
    rows: tuple
    # Flattened historical input has lost empty-cell positions. Only ordered
    # nonempty cells can be proved; never invent their missing column locations.
    flattened: bool = False


def weekly_schedule(description):
    try:
        tables = read_body(description).tables
    except AiJobError:
        if re.search(r'(?m)^\s*\|\s*시간(?:\s*[/·]\s*요일)?\s*\|\s*'+WEEKDAY+r'\s*\|', description):
            # A malformed weekly matrix is not absence of a schedule. Do not
            # let an aggregate response bypass validation by hiding its source.
            raise
        tables = ()  # Unsupported source markup stays data, not executable HTML.
    matrices = []
    for table in tables:
        headers = tuple(plain(h) for h in table.headers)
        if re.fullmatch(r'시간(?:\s*[/·]\s*요일)?', headers[0]) and all(re.fullmatch(WEEKDAY, h) for h in headers[1:]):
            if not all(re.fullmatch(CLOCK, plain(r[0])) for r in table.rows):
                raise AiJobError('ai_schema_error')
            days = tuple(key(h).replace('요일', '') for h in headers[1:])
            clocks = tuple(plain(r[0]) for r in table.rows)
            if len(days) != len(set(days)) or len(clocks) != len(set(clocks)):
                raise AiJobError('ai_schema_error')
            matrices.append(WeeklySchedule(('시간', *headers[1:]), tuple(tuple(plain(c) for c in r) for r in table.rows)))
    if matrices:
        if len(matrices) != 1:
            raise AiJobError('ai_schema_error')
        return matrices[0]
    lines = [plain(line) for line in description.splitlines() if line.strip()]
    for start, line in enumerate(lines):
        if not re.fullmatch(r'시간\s*[/·]\s*요일', line):
            continue
        index = start + 1; days = []
        while index < len(lines) and re.fullmatch(WEEKDAY, lines[index]):
            days.append(lines[index]); index += 1
        if len(days) < 2 or len(days) != len(set(days)):
            raise AiJobError('ai_schema_error')
        rows = []
        while index < len(lines) and re.fullmatch(CLOCK, lines[index]):
            clock = lines[index]; index += 1; cells = []
            while index < len(lines):
                value = lines[index]
                if re.fullmatch(ORDINAL, value):
                    cells.append(value)
                elif cells and re.fullmatch(r'[（(][^()（）]+[）)]', value):
                    cells[-1] += value
                else:
                    break
                index += 1
            if not cells or len(cells) > len(days):
                raise AiJobError('ai_schema_error')
            rows.append((clock, *cells))
        if rows:
            return WeeklySchedule(('시간', *days), tuple(rows), True)
        raise AiJobError('ai_schema_error')
    return None


def weekly_input_evidence(description):
    """Ephemeral AI input from current confirmed text, never observed fallback.

    A null is a known empty source cell, not an unknown/missing cell. Historical
    flattened tables cannot prove column positions and must be reviewed first.
    No DB/summary schema change, source lookup or inferred table repair.
    """
    source = weekly_schedule(description)
    if not source:
        return None
    if source.flattened:
        raise AiJobError('ai_schema_error')
    return {'headers': list(source.headers),
            'rows': [[None if plain(c) in EMPTY_CELL else c for c in row] for row in source.rows]}


def public_roles(facts):
    matrix = weekly_schedule(facts['description'])
    cells = {key(cell) for row in matrix.rows for cell in row[1:]} if matrix else set()
    # A standalone language annotation is table data only when actually attached
    # to a source cell. Language eligibility such as "일본어 가능자만" stays.
    annotations = {key(m[0]) for cell in cells for m in re.finditer(r'[（(][^()（）]+[）)]', cell)}
    table_rows={key('| '+' | '.join(row)+' |') for row in matrix.rows} if matrix and not matrix.flattened else set()
    roles = {name: [] for name in ('eligibility', 'capacity', 'schedule', 'booking')}
    for value in dict.fromkeys(facts['conditions']):
        text = plain(value)
        if key(text) in table_rows:
            continue
        target=re.fullmatch(r'(?:참가\s*대상|대상)\s*[:：]\s*(.+)', text)
        if target and (key(target[1]) == key(facts['target_raw']) or
                {key(target[1]),key(facts['target_raw'])} <= {'제한없음','누구나'}):
            continue  # Same bare audience; qualified restrictions never match.
        if matrix and (re.fullmatch(ORDINAL, text) and any(key(text) == re.sub(r'[（(].*', '', c) for c in cells)
                       or key(text) in annotations):
            continue  # Kept in the source and schedule table, not eligibility.
        if re.match(CAPACITY + r'\s*[:：]', text):
            role = 'capacity'
        elif re.match(SCHEDULE + r'\s*[:：]', text) and not re.search(RESTRICTION, text):
            role = 'schedule'
        elif re.match(r'(?:예약|신청|접수)\s*(?:방법|절차|단계)\s*[:：]', text):
            role = 'booking'
        elif ('→' in text or '->' in text) and re.search(r'예약|신청|접수', text) and not re.search(RESTRICTION, text):
            role = 'booking'
        else:
            role = 'eligibility'
        roles[role].append(value)
    return roles


def validate_weekly_schedule(content, description):
    """Bind each generated clock row to its source cells, not a number bag."""
    source = weekly_schedule(description)
    generated = [t for t in read_body(content).tables if re.fullmatch(r'시간(?:\s*[/·]\s*요일)?',plain(t.headers[0]))
                 and all(re.fullmatch(WEEKDAY, plain(h)) for h in t.headers[1:])]
    if not source:
        if generated:
            raise AiJobError('ai_schema_error')
        return
    if source.flattened:
        # Nonempty cell order cannot prove weekdays or empty positions. Even a
        # plausible seven-column generated table cannot repair lost evidence.
        raise AiJobError('ai_schema_error')
    if len(generated) != 1:
        raise AiJobError('ai_schema_error')
    table = generated[0]
    if ('시간', *(key(h).replace('요일', '') for h in table.headers[1:])) != tuple(key(h).replace('요일', '') for h in source.headers):
        raise AiJobError('ai_schema_error')
    rows = tuple(tuple(plain(c) for c in row) for row in table.rows)
    def cell_key(cell):
        return None if plain(cell) in EMPTY_CELL else key(cell)
    if tuple(tuple(cell_key(c) for c in row) for row in rows) != tuple(tuple(cell_key(c) for c in row) for row in source.rows):
        raise AiJobError('ai_schema_error')


def booking_covered(value, method):
    """Only exact text or every quoted search/selection token in an arrow chain.

    Unquoted or mixed procedures are retained verbatim. This is not a semantic
    paraphrase engine; numbers/URLs and restrictions are never dropped here.
    """
    if key(plain(value)) in key(method):
        return True
    quoted = re.findall(r'[“「‘\"]([^”」’\"]+)[”」’\"]', value)
    tokens = [key(v) for v in quoted if len(key(v)) >= 2]
    return bool(tokens and all(v in key(method) for v in tokens)
                and re.search(r'검색', method) and re.search(r'선택', method)
                and all(n in re.findall(r'\d+', method) for n in re.findall(r'\d+', value))
                and not re.search(r'https?://|'+RESTRICTION, value))


def nationality_rule(text):
    # Whole simple foreign-only sentences only. Added age, visa, companion,
    # residence, reservation or other clauses make the rule ineligible for
    # deduplication. Negation direction is part of the signature.
    text = re.sub(r'\s+|[.。]', '', plain(text))
    if re.fullmatch(r'(?:(?:해설|프로그램|체험|교육)(?:은|는))?외국인(?:관람객)?(?:을|관람객을)?대상으로운영(?:하므로|하며)'
                    r'내국인(?:은)?참여(?:가)?(?:불가합니다|할수없습니다)', text):
        return ('foreign', 'korean_denied')
    return None


def recurrence_rule(text):
    text = key(plain(text))
    match = re.fullmatch(r'(?:'+SCHEDULE+r'[:：]|(?:해설|프로그램|체험|교육)(?:은|는)(?:약\d+분이며)?)'
        r'([월화수목금토일])(?:요일)?[~～]([월화수목금토일])요일'
        r'(?:에(?:운영|진행)합니다)?[（(]([월화수목금토일])요일[,.·、]공휴일제외[）)][.。]?', text)
    return match.groups() if match else None


def clean_role_repetitions(content, sections, facts):
    """Omit a canonical rule only when one complete generated sentence covers it.

    Preserve compound prose and any uncertain equivalence. No arbitrary substring
    deletion. Booking/capacity already have their own role and do not pass here.
    """
    target=optional_section(content, '[대상]')
    schedule=optional_section(content, '[일정 안내]')
    result=dict(sections)
    for header, body, label, parser in (
            ('[대상]', target, '참가 조건', nationality_rule),
            ('[일정 안내]', schedule, None, recurrence_rule)):
        covered={rule for line in body.splitlines() if (rule:=parser(line))}
        kept=[]
        for line in result[header].splitlines():
            value=plain(line)
            if label:
                value=re.sub(r'^'+label+r'\s*[:：]\s*', '', value)
            if parser(value) not in covered or parser(value) is None:
                kept.append(line)
        result[header]=re.sub(r'\n?\*\*진행 일정:\*\*\s*\Z', '', '\n'.join(kept))
    return content,result


def optional_section(content, header):
    from ingest.ai_worker import KO_SECTION_HEADERS
    boundary='|'.join(re.escape(h) for h in KO_SECTION_HEADERS)
    match=re.search(r'(?ms)^\s*'+re.escape(header)+r'[ \t]*(.*?)(?=^\s*(?:'+boundary+r')|\Z)', content)
    return match[1].strip() if match else ''
