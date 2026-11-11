"""Source-backed Seoul condition projection; never mutates stored facts.

Legacy conditions are keyword-selected lines, not complete eligibility rules.
Only uniquely located continuations and whole, bounded equivalences are used.
Unknown qualifiers remain visible rather than being guessed or discarded.
"""
import re

from ingest.body_markdown import inline_text, read_body


def plain(value):
    return re.sub(r'^[\s○❍●☞▹▶■□*+\-]+', '', inline_text(value)).strip()


def key(value):
    return re.sub(r'\s+', '', plain(value)).rstrip('.。')


_BOUNDARY = re.compile(r'^\s*(?:[-*+○❍●☞▹▶■□]|\d+[.)]|\[|\||https?://)')
_HEADING = re.compile(r'^(?:교육대상|교육장 규정 및 신청시 주의사항)$')
_CONTINUATION = re.compile(r'(?:\s후|분들은|경우에는|경우에|경우)\s*$')


def projected_conditions(facts):
    """Repair legacy slices from current description only, not old observations.

    Duplicate source occurrences are ambiguous. A marked next item, heading,
    table, blank paragraph, URL or independently labelled field is a boundary.
    """
    lines = facts['description'].splitlines()
    result = []
    consumed = set()
    for value in dict.fromkeys(facts['conditions']):
        if key(value) in consumed:
            continue
        matches = [i for i, line in enumerate(lines) if key(line) == key(value)]
        text = plain(value)
        if len(matches) == 1:
            index = matches[0]
            if _HEADING.fullmatch(text) and index + 1 < len(lines) and lines[index + 1].strip():
                continue  # Empty source label, never an operator's qualified rule.
            for following in lines[index + 1:index + 4]:
                if not _CONTINUATION.search(text):
                    break
                if (not following.strip() or _BOUNDARY.match(following)
                        or re.match(r'^[^:：]{1,30}[:：]', following.strip())
                        or _HEADING.fullmatch(plain(following))):
                    break
                text += ' ' + following.strip()
                consumed.add(key(following))
        # Explicitly conjoined capacity and application deadline, not an
        # arbitrary comma split. Preserve both numbers and obligation.
        compound = re.fullmatch(r'교육장\s*신청\s*인원은\s*최대\s*(\d+)명\s*제한이며,\s*'
                                r'반드시\s*교육희망일\s*(\d+)일\s*전에\s*교육\s*신청을\s*해야\s*함', text)
        values = ([f'정원: 최대 {compound[1]}명', f'신청 방법: 교육희망일 {compound[2]}일 전까지 신청해야 합니다.']
                  if compound else [text])
        for projected in values:
            if projected not in result:
                result.append(projected)
    return result


def additional_role(text):
    """Positive contextual labels only; participant restrictions still win."""
    text = plain(text)
    if re.match(r'교육\s*신청\s*가능\s*(?:요일|시간)\s*[:：]', text):
        return 'schedule'
    if re.match(r'교육희망일에\s*신청인원', text):
        return 'schedule'
    # An age/residence/language/guardian restriction is not a booking procedure.
    if re.search(r'보호자|동반|거주|국적|비자|학년|연령|\d+\s*세|가능자|소지자', text):
        return None
    if (re.match(r'(?:교육신청은|달력에\s*신청|.*홈페이지\s*[-–])', text)
            or re.match(r'(?:반드시\s*)?사전\s*예약\s*(?:및|·)', text)
            or re.match(r'(?:\d+\s*명\s*이상의?\s*)?단체(?:교육\s*)?신청', text)
            or re.match(r'(?:당일\s*)?명단\s*변경', text)
            or re.match(r'교육장\s*신청\s*인원', text)
            or re.match(r'교육희망일에\s*신청인원', text)):
        return 'booking'
    return None


def _sentences(body):
    """No splitting decimal numbers, addresses, table cells or continuations."""
    for line in body.splitlines():
        if '|' in line or line[:1].isspace():
            continue
        yield from (plain(s) for s in re.split(r'(?<=[.!?。])\s+', line) if s.strip())


def _advice_signature(text):
    # Whole simple clauses. Extra qualifications/negation prevent a match.
    text = key(text)
    if re.fullmatch(r'(?:반드시)?사전예약(?:및|·)문의후(?:교육)?신청(?:바랍니다|하세요)', text):
        return ('advance_reservation_inquiry',)
    m = re.fullmatch(r'(?:달력의)?(?:교육신청은)?(?:하얀색으로떠있는|흰색)날짜만신청가능(?:합니다)?', text)
    if m:
        return ('white_calendar_dates',)
    m = re.fullmatch(r'(?:변경된?명단은)?교육(?:시작)?일(\d+)일전까지(?:변경된?명단을)?'
                     r'(?:이메일|메일)(?:로)?(?:제출해야하며|보내주시면됩니다)', text)
    if m:
        return ('changed_roster_days', int(m[1]))
    text = re.sub(r'^(?:신청방법|예약절차|신청안내)[:：]', '', text)
    m = re.fullmatch(r'(?:선착순사전예약이며)?교육희망일(\d+)일전까지신청(?:해야합니다|해야함)', text)
    if m:
        return ('application_days', int(m[1]))
    m = re.fullmatch(r'당일명단변경은절대로불가능하며명단이바뀔시단체교육시작일(\d+)일전까지'
                     r'변경된명단을메일로보내주시면됩니다', text)
    if not m:
        m = re.fullmatch(r'변경명단은교육시작일(\d+)일전까지이메일로제출해야하며당일변경은불가합니다', text)
    if m:
        return ('roster_change_and_same_day_denied', int(m[1]))
    m = re.fullmatch(r'(\d+)명이상의단체교육신청은반드시교육장\(☎?([\d-]+)\)으로별도로전화후예약가능', text)
    if m:
        return ('group_phone', int(m[1]), m[2])
    # This complete positive clause can carry a following roster instruction;
    # that additional instruction is retained verbatim in generated prose.
    m = re.fullmatch(r'(\d+)명이상단체는([\d-]+)로사전전화하여교육일을협의한뒤,'
                     r'이름·생년월일·성별·휴대폰번호명단을([^\s]+@[^\s]+)로보내야합니다', text)
    if m:
        return ('group_phone_roster', int(m[1]), m[2], m[3])
    m = re.fullmatch(r'단체신청시신청자의이름,생년월일,성별,휴대폰번호를적어'
                     r'([^\s]+@[^\s]+)로보내주시기바랍니다', text)
    if m:
        return ('group_roster', m[1])
    m = re.fullmatch(r'달력에신청가능하신날짜가보이지않으시는분들은(.+?)홈페이지-'
                     r'(.+?)탭을클릭하여링크로넘어와야날짜확인이가능합니다', text)
    if m:
        return ('calendar_entry', m[1], m[2])
    m = re.fullmatch(r'날짜가보이지않으면(.+?)홈페이지의[‘\'「](.+?)[’\'」]탭을통해접속하세요', text)
    if m:
        return ('calendar_entry', m[1], m[2])
    m = re.fullmatch(r'교육희망일에신청인원이(\d+)명이하의경우교육장운영상교육진행이어려우며'
                     r'교육진행불가시전날개별연락후다른교육일정안내', text)
    if m:
        return ('low_enrollment_notice', int(m[1]))
    m = re.fullmatch(r'(?:\d+명이상이면교육확정으로안내되지만,)?신청자가(\d+)명이하이면진행이어려울수있습니다\.'
                     r'진행불가시전날개별연락하여다른일정을안내합니다', text)
    if m:
        return ('low_enrollment_notice', int(m[1]))
    return None


def covered_condition(value, body):
    """Exact whole statement or explicitly recognized complete equivalent only.

    No substring/number-bag coverage: '필수' is not covered by '필수 아님'.
    Safe uncertainty costs an extra note, never a silently lost condition.
    """
    source = key(value)
    signature = _advice_signature(value)
    # A following exception changes applicability. Don't use isolated prose to
    # erase the source in that case, even when an earlier sentence is identical.
    if re.search(r'단,|다만|예외|에 한해|에만 해당', body):
        return False
    sentences = list(_sentences(body))
    for sentence in [*sentences, *(a + ' ' + b for a, b in zip(sentences, sentences[1:]))]:
        sentence = re.sub(r'^(?:참가 조건|예약 절차|신청 안내)\s*[:：]\s*', '', sentence)
        if source == key(sentence):
            return True
        if signature is not None:
            proof = _advice_signature(sentence)
            if signature == proof:
                return True
            if proof and proof[0] == 'group_phone_roster':
                if signature == ('group_phone', proof[1], proof[2]) or signature == ('group_roster', proof[3]):
                    return True
    return False


def weekly_covered(value, body):
    """Exact weekday-to-clock mapping in a two-column table, not number sets."""
    text = key(value)
    heading = re.fullmatch(r'교육신청가능(요일|시간)[:：](.+)', text)
    if not heading:
        return False
    tables = [table for table in read_body(body).tables if tuple(table.headers) == ('요일', '시간')]
    if len(tables) != 1:
        return False
    days_pattern = r'[월화수목금토일](?:요일)?(?:[,·][월화수목금토일](?:요일)?)*'
    def days(text):
        return set(re.findall(r'[월화수목금토일]', text.replace('요일', ''))) if re.fullmatch(days_pattern, text) else None
    actual = {}
    for day_text, clock_text in tables[0].rows:
        names = days(key(day_text))
        clocks = re.fullmatch(r'(\d{1,2}):([0-5]\d)[~～](\d{1,2}):([0-5]\d)', key(clock_text))
        if not names or not clocks or names & actual.keys():
            return False
        pair = tuple(map(int, clocks.groups()))
        if pair[0] > 23 or pair[2] > 23:
            return False
        actual.update(dict.fromkeys(names, pair))
    remaining = heading[2]
    if heading[1] == '요일':
        holiday = remaining.startswith('(공휴일제외)')
        if holiday:
            remaining = remaining[len('(공휴일제외)'):]
        return days(remaining) == set(actual) and (not holiday or
            any(key(s) == '공휴일을제외한일정입니다' for s in _sentences(body)))
    expected = {}
    for part in remaining.split('/'):
        m = re.fullmatch(r'('+days_pattern+r')(오전|오후)?(\d{1,2}):([0-5]\d)[~～](\d{1,2}):([0-5]\d)', part)
        if not m:
            return False
        names = days(m[1])
        if names & expected.keys():
            return False
        start_h, start_m, end_h, end_m = map(int, m.groups()[2:])
        if m[2] == '오후':
            start_h += 12 if start_h < 12 else 0
            end_h += 12 if end_h < 12 else 0
        elif m[2] == '오전':
            start_h = 0 if start_h == 12 else start_h
            end_h = 0 if end_h == 12 else end_h
        expected.update(dict.fromkeys(names, (start_h, start_m, end_h, end_m)))
    return bool(expected) and expected == actual


def clean_projected_duplicates(content, sections, facts):
    """Remove old canonical copies, then preserve one correctly placed copy.

    Legacy generated input is supported for local reassembly, not bulk editing.
    Only exact canonical rows from these current facts qualify for relocation.
    """
    from ingest.seoul_fact_roles import public_roles, optional_section
    from ingest.ai_worker import KO_SECTION_HEADERS
    roles = public_roles(facts)
    originals = {key(v) for v in facts['conditions']
                 if additional_role(v) or _HEADING.fullmatch(plain(v)) or _CONTINUATION.search(v)}
    originals.update(key(v) for values in roles.values() for v in values if additional_role(v))
    old_keys = {key(v) for v in facts['conditions']}
    originals.update(key(v) for v in projected_conditions(facts) if key(v) not in old_keys)
    if not originals:
        return content, sections
    lines = []
    current = None
    for line in content.splitlines():
        if line.strip() in KO_SECTION_HEADERS:
            current = line.strip()
        match = re.fullmatch(r'\s*- \*\*(?:참가 조건|예약 절차|신청 안내|진행 일정):\*\*\s*(.+)', line)
        if current != '[한 줄 요약]' and match and key(match[1]) in originals:
            continue
        lines.append(line)
    content = '\n'.join(lines)
    result = dict(sections)
    # Same complete statement in its destination is sufficient, never unrelated
    # sentences spread across the document or the canonical row itself.
    for header in ('[대상]', '[일정 안내]', '[신청 방법]'):
        proof = optional_section(content, header)
        kept = []
        for line in result[header].splitlines():
            match = re.fullmatch(r'- \*\*(?:참가 조건|예약 절차|신청 안내|진행 일정):\*\*\s*(.+)', line)
            if (match and key(match[1]) in originals
                    and (covered_condition(match[1], proof) or weekly_covered(match[1], proof))):
                continue
            kept.append(line)
        result[header] = '\n'.join(kept)
    # Remove only the separately represented, fully matched parenthetical age
    # rule; the API audience list itself is still displayed and stored intact.
    target = re.fullmatch(r'(.+)\(실습 교육 특성상 초등학생의 경우 고학년이상만 접수가능합니다\.\)', facts['target_raw'])
    proof = optional_section(content, '[대상]')
    if target and any(key(s) == '초등학생은고학년이상만접수가능합니다' for s in _sentences(proof)):
        result['[대상]'] = result['[대상]'].replace('- **대상:** ' + facts['target_raw'], '- **대상:** ' + target[1])
    return content, result
