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
        if re.search(r'(?m)^\s*\|\s*시간(?:\s*[/·]\s*요일)?\s*\|', description):
            # A malformed weekly matrix is not absence of a schedule. Do not
            # let an aggregate response bypass validation by hiding its source,
            # including a missing first weekday header.
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
    # A neutral API audience preface is not an extra eligibility condition.
    # Remove only this bounded preface for comparison, never from public prose.
    text = _AUDIENCE_PREFACE.sub('', text, count=1)
    if re.fullmatch(r'(?:(?:해설|프로그램|체험|교육)(?:은|는))?외국인(?:관람객)?(?:을|관람객을)?대상'
                    r'(?:으로운영(?:하므로|하며)|(?:해설|프로그램|체험|교육)(?:로|이므로|이며))'
                    r'내국인(?:은)?(?:참여|참가)(?:가)?(?:불가합니다|할수없습니다)', text):
        return ('foreign', 'korean_denied')
    return None


def recurrence_rule(text):
    text = key(plain(text))
    match = re.fullmatch(r'(?:'+SCHEDULE+r'[:：]|(?:해설|프로그램|체험|교육)(?:은|는)(?:약\d+분이며)?)'
        r'([월화수목금토일])(?:요일)?[~～]([월화수목금토일])요일'
        r'(?:에(?:운영|진행)합니다)?[（(]([월화수목금토일])요일[,.·、]공휴일제외[）)][.。]?', text)
    if match:
        return match.groups()
    match = re.fullmatch(r'(?:(?:해설|프로그램|체험|교육)(?:은|는))?'
        r'([월화수목금토일])(?:요일)?[~～]([월화수목금토일])요일'
        r'(?:에)?(?:운영|진행)(?:하며|합니다)[,]?'
        r'([월화수목금토일])요일[·,]공휴일(?:은|을)?제외합니다[.。]?', text)
    return match.groups() if match else None


_AUDIENCE_PREFACE = re.compile(
    r'^(?:일반(?:안내|대상)|원문(?:안내|대상))(?:은|는)'
    r'[‘“\'"「]?(?:누구나|제한없음)[’”\'"」]?'
    r'(?:이나|로안내되어있으나|로안내되어있지만|로안내되지만),')


def _prose_sentences(body):
    """Coverage evidence only; retain generated paragraphs verbatim.

    Read sentence boundaries outside tables/indented continuations. Don't split
    arbitrary commas, parentheses, URLs or numeric values into new facts.
    """
    for line in body.splitlines():
        if '|' in line or line[:1].isspace():
            continue
        yield from re.split(r'(?<=[.!?。])(?=\s|$)', inline_text(line))


def _coverage_body(body, canonical):
    # A previously assembled canonical row cannot prove its own redundancy.
    # Coverage must come from another same-role sentence/explicit procedure.
    rows={key(plain(line)) for line in canonical.splitlines() if line.strip()}
    return '\n'.join(line for line in body.splitlines() if key(plain(line)) not in rows)


def _without_covered_rows(body, rows):
    keys={key(plain(line)) for line in rows}
    lines=body.splitlines();kept=[]
    for index,line in enumerate(lines):
        continuation=index+1<len(lines) and lines[index+1][:1].isspace() and lines[index+1].strip()
        if ('|' not in line and not line[:1].isspace() and not continuation
                and key(plain(line)) in keys):
            continue
        kept.append(line)
    return re.sub(r'\n?\*\*진행 일정:\*\*\s*\Z', '', '\n'.join(kept))


def _unrestricted_audience_covered(body, facts):
    if key(facts['target_raw']) not in {'누구나', '제한없음'}:
        return False
    # Coverage is a statement about the raw/general audience, never proof that
    # everyone can participate despite a separately stated restriction.
    return any(_AUDIENCE_PREFACE.match(key(plain(line))) for line in body.splitlines()
               if '|' not in line and not line[:1].isspace())


def _application_methods_covered(methods, body):
    """All reviewed method kinds must have explicit method-role evidence.

    Contacts are not phone applications. Keep conditional onsite prose intact;
    only a redundant bare method list may be omitted. Uncertain/negated methods
    and unique canonical continuations stay rather than being inferred.
    """
    text = inline_text(body)
    proofs = set()
    blocked = set()
    patterns = {
        'internet': r'(?:온라인|인터넷)\s*(?:예약|신청)(?!자|번호|시간)',
        'onsite': r'(?:현장|방문)\s*(?:접수|신청)',
        'phone': r'전화\s*(?:신청|예약|접수)',
    }
    for kind, pattern in patterns.items():
        matches = list(re.finditer(pattern, text))
        # Never count a negated method as coverage, even if the same noun occurs
        # elsewhere. No global prohibition list or cross-section inference.
        tails=[re.split(r'[.!?。\n]',text[m.end():],maxsplit=1)[0] for m in matches]
        negative = any(re.search(r'불가|금지|없|하지\s*(?:않|마)|할\s*수\s*없|안\s*(?:함|합니다|됨|됩니다)',
                                tail) for tail in tails)
        if negative:
            blocked.add(kind)
        positive=any(re.match(r'\s*(?:[,;:/]|$|(?:은|는|이|가|을|를)?\s*'
                             r'(?:가능|진행|신청|예약|접수|할\s*수\s*있|후|로|필수|해야))',tail) for tail in tails)
        if positive and not negative:
            proofs.add(kind)
    # The source-specific named reservation platform plus an explicit ordered
    # search -> selection -> booking procedure proves the internet method.
    # A URL, place name, query/contact or stray reservation word alone does not.
    if 'internet' not in blocked and re.search(r'(?:서울시\s*)?공공서비스\s*예약에서[^\n.。]*검색\s*(?:→|->)'
                 r'[^\n.。]*선택\s*(?:→|->)[^\n.。]*예약\s*진행', text):
        proofs.add('internet')
    return bool(methods and set(methods) <= proofs)


def clean_role_repetitions(content, sections, facts):
    """Omit a canonical rule only when bounded same-role evidence covers it.

    Preserve compound prose and any uncertain equivalence. No arbitrary substring
    deletion: compare individual complete sentences without deleting them.
    """
    target=optional_section(content, '[대상]')
    schedule=optional_section(content, '[일정 안내]')
    result=dict(sections)
    omitted={header:[] for header in ('[대상]','[일정 안내]','[신청 방법]')}
    for header, body, label, parser in (
            ('[대상]', target, '참가 조건', nationality_rule),
            ('[일정 안내]', schedule, None, recurrence_rule)):
        proof_body=_coverage_body(body,sections[header])
        covered={rule for sentence in _prose_sentences(proof_body) if (rule:=parser(sentence))}
        kept=[]
        canonical_lines=result[header].splitlines()
        for index,line in enumerate(canonical_lines):
            continuation=index+1<len(canonical_lines) and canonical_lines[index+1][:1].isspace() and canonical_lines[index+1].strip()
            if '|' in line or line[:1].isspace() or continuation:
                kept.append(line)
                continue
            value=plain(line)
            if label:
                value=re.sub(r'^'+label+r'\s*[:：]\s*', '', value)
            if (header == '[대상]' and re.fullmatch(r'대상\s*[:：]\s*(?:누구나|제한없음)', value)
                    and _unrestricted_audience_covered(proof_body, facts)):
                omitted[header].append(line)
                continue
            rule=parser(value)
            # A weekday signature cannot cover an additional duration/count in
            # the canonical source row. Keep that whole row and its qualifiers.
            if parser is recurrence_rule and re.search(r'\d', value):
                rule=None
            if rule not in covered or rule is None:
                kept.append(line)
            else:
                omitted[header].append(line)
        result[header]=re.sub(r'\n?\*\*진행 일정:\*\*\s*\Z', '', '\n'.join(kept))
    method=optional_section(content, '[신청 방법]')
    expected=' / '.join(dict(internet='인터넷 예약', onsite='현장 접수', phone='전화 신청')[v]
                        for v in facts['application_methods'])
    lines=result['[신청 방법]'].splitlines()
    if _application_methods_covered(facts['application_methods'], _coverage_body(method,sections['[신청 방법]'])):
        kept=[]
        for index,line in enumerate(lines):
            if (re.fullmatch(r'신청 방법\s*[:：]\s*'+re.escape(expected), plain(line))
                    and not (index+1<len(lines) and lines[index+1][:1].isspace() and lines[index+1].strip())):
                omitted['[신청 방법]'].append(line)
            else:
                kept.append(line)
        result['[신청 방법]']='\n'.join(kept)
    # Handle already-assembled local input without deleting the only copy of a
    # fact. Only proven redundant canonical rows in the same section qualify.
    from ingest.ai_worker import KO_SECTION_HEADERS
    boundary='|'.join(re.escape(h) for h in KO_SECTION_HEADERS)
    for header,rows in omitted.items():
        if rows:
            content=re.sub(r'(?ms)(^\s*'+re.escape(header)+r'[ \t]*)(.*?)(?=^\s*(?:'+boundary+r')|\Z)',
                lambda m:m[1]+'\n'+_without_covered_rows(m[2],rows)+'\n',content,count=1)
    return content,result


def optional_section(content, header):
    from ingest.ai_worker import KO_SECTION_HEADERS
    boundary='|'.join(re.escape(h) for h in KO_SECTION_HEADERS)
    match=re.search(r'(?ms)^\s*'+re.escape(header)+r'[ \t]*(.*?)(?=^\s*(?:'+boundary+r')|\Z)', content)
    return match[1].strip() if match else ''
