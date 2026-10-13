"""Bounded checks for explicit reviewed quantities and schedule lines.

No model calls, calendar expansion, source lookup or inferred sessions.
"""
from __future__ import annotations

import re
from datetime import date
from ingest.ai_errors import AiJobError
from ingest.body_sections import normalize_schedule_heading
from ingest.body_markdown import comparison_text, inline_text, read_body, schedule_table_lines, schedule_tables
from ingest.myseoul_ai_support import schedule_values
from ingest.translation_validation import _dates_and_times, _entry, _quantities, _amounts, _durations


PUBLIC_FACT_SECTIONS = {
    '대상': '[대상]', '참가 조건': '[대상]', '참가 대상 근거': '[대상]',
    '거주 조건': '[대상]', '거주 조건 근거': '[대상]', '모집 인원': '[대상]',
    '신청기간': '[일정 안내]', '신청 기간': '[일정 안내]',
    '진행기간': '[일정 안내]', '진행 기간': '[일정 안내]', '운영 기간': '[일정 안내]',
    '개최 기간': '[일정 안내]', '신청 마감': '[일정 안내]',
    '진행 일정': '[일정 안내]', '집결 안내': '[일정 안내]',
    '장소': '[주요 내용]', '진행 방식': '[주요 내용]',
    '비용': '[주요 내용]', '비용 안내': '[주요 내용]',
    '신청 방법': '[신청 방법]', '신청 링크': '[신청 방법]',
}


def _public_fact_row(line: str):
    plain = re.sub(r'^\s*[-+*]\s+', '', inline_text(line)).strip()
    if re.fullmatch(r'https?://\S+', plain):
        return None
    match = re.fullmatch(r'([^:：\n]+)\s*[:：]\s*(.+)', plain)
    return (match[1].strip(), match[2].strip()) if match else None


def _same_public_row(left: str, right: str) -> bool:
    # Exact text/role equality only. URL paths, numeric roles and qualifiers
    # remain opaque; no substring, number-set or prose meaning inference.
    a, b = _public_fact_row(left), _public_fact_row(right)
    if a and b:
        return a == b
    if a or b:
        labeled, bare = (a, right) if a else (b, left)
        return labeled[0] in {'대상', '신청 방법', '신청 링크'} and labeled[1] == inline_text(bare).strip()
    return inline_text(left).strip() == inline_text(right).strip()


def merge_reviewed_sections(content: str, reviewed: dict[str, str]) -> str:
    """Place public facts in their section, never below the last application.

    Keep unique generated instructions and inseparable prose/table conditions.
    Deduplicate only identical complete rows. A section heading is not data.
    The summary is intentionally allowed to repeat useful facts for readability.
    """
    from ingest.ai_worker import KO_SECTION_HEADERS
    headers = list(KO_SECTION_HEADERS)
    boundary = '|'.join(re.escape(h) for h in headers)
    matches = list(re.finditer(r'(?ms)^[ \t]*('+boundary+r')[ \t]*(.*?)(?=^[ \t]*(?:'+boundary+r')(?=[ \t]|$)|\Z)', content))
    if (not matches or content[:matches[0].start()].strip()
            or len({m[1] for m in matches}) != len(matches)):
        raise AiJobError('ai_schema_error')
    sections = {m[1]: m[2].strip() for m in matches}
    if not sections.get('[한 줄 요약]') or not sections.get('[주요 내용]'):
        raise AiJobError('ai_schema_error')
    canonical = [line for value in reviewed.values() for line in value.splitlines() if line.strip()]
    method_rows = [v for v in reviewed.get('[신청 방법]', '').splitlines() if v.strip()]
    links = {row[1] for v in method_rows if (row := _public_fact_row(v)) and row[0] == '신청 링크'}
    methods = {(_public_fact_row(v) or ('', inline_text(v).strip()))[1] for v in method_rows
               if not _public_fact_row(v) or _public_fact_row(v)[0] == '신청 방법'}
    kept = {h: [] for h in headers}
    for header, text in sections.items():
        if header == '[한 줄 요약]':
            kept[header] = [text]
            continue
        # Remove an exact previously merged block as a whole. In particular,
        # don't leave a table/header behind when applying this function twice.
        own = reviewed.get(header, '').strip()
        if own:
            text = re.sub(r'(?m)^'+re.escape(own)+r'(?=\n|$)', '', text)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            row = _public_fact_row(line)
            # Tables and indented continuations are never individually removed
            # or moved. A date/activity belongs to its existing row/parent.
            if '|' in line or (line[:1].isspace() and line.strip()):
                kept[header].append(line)
                continue
            continuation = index+1 < len(lines) and lines[index+1][:1].isspace() and lines[index+1].strip()
            if line.strip() and not continuation and any(_same_public_row(line, v) for v in canonical):
                continue
            # A pure "<confirmed method>: <confirmed URL>" row carries no
            # extra instructions. Keep contact/QR/qualification prose intact.
            if header == '[신청 방법]' and row and not continuation and row[1] in links and row[0] in methods:
                continue
            destination = (PUBLIC_FACT_SECTIONS.get(row[0], header)
                           if header == '[신청 방법]' and row and not continuation else header)
            kept[destination].append(line)
    for header, value in reviewed.items():
        if header not in kept:
            raise AiJobError('ai_schema_error')
        if value.strip():
            while kept[header] and not kept[header][-1].strip():
                kept[header].pop()
            kept[header].extend(['', value])
    result = '\n\n'.join(h+'\n'+ '\n'.join(kept[h]).strip() for h in headers
                         if '\n'.join(kept[h]).strip())
    # No unsectioned internal checklist can silently become public method text.
    if re.search(r'(?m)^\s*확인한 분류·참가 안내\s*$', result):
        raise AiJobError('ai_schema_error')
    for line in '\n'.join(kept['[신청 방법]']).splitlines():
        row = _public_fact_row(line)
        if row and (row[0] == '분류' or PUBLIC_FACT_SECTIONS.get(row[0], '[신청 방법]') != '[신청 방법]'):
            # Ambiguous/nested records are not silently discarded to force
            # completion. Use the worker's existing pre-translation failure.
            raise AiJobError('ai_schema_error')
    return result

_DATED_LINE = (r'^(?:제?\d+\s*(?:회차|차)\s*[:.)-]?\s*)?'
               r'(?:(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}-\d{2}-\d{2})')


def _plain_schedule_line(line: str) -> str:
    return re.sub(r'^[^\w가-힣\[]+', '', inline_text(line)).strip('[]:： ')


def _schedule_heading_or_invitation(line: str) -> bool:
    """Recognize only factless headings/invitations, not arbitrary prose.

    A weekday in a class title is not a session. Explicit recurrence, dates,
    counts, durations, money and restrictions always prevent removal.
    """
    text = inline_text(line).strip()
    values = schedule_values(text)
    if (any(v for key, v in values.items() if key != 'weekdays')
            or _dates_and_times(text) or _durations(text) or _amounts(text, japanese=False)
            or _quantities(text, japanese=False)
            or re.search(r'매주|격주|매월|매일|필수|의무|조건|자격|제한|전용|한정|선착순|'
                         r'보호자|동반|지참|제출|출석|참석|국적|비자|거주|연령|\d+\s*살|'
                         r'불가|금지|않|없|이상|이하|미만|초과|만\s*신청|'
                         r'무료|유료|할인|면제|환불|납부|마감|종료|취소|변경|예정', text)):
        return False
    return bool(
        re.fullmatch(r'<[^<>\n]+(?:모집|신청|수업|교육|일정)\s*안내\s*>', text)
        or re.fullmatch(r'(?:교육|수업|강의|행사|프로그램|진행|운영)\s*(?:일정|일시)(?:\s*안내)?',
                        _plain_schedule_line(text))
        or re.fullmatch(r'.+(?:신청|모집)\s*안내\s*(?:드립니다|드려요|합니다)[.!。！]*', text)
        or re.fullmatch(r'(?:많은\s*)?관심과\s*참여\s*부탁드립니다[.!。！]*', text)
    )


def schedule_block(lines: list[str]) -> str:
    """Keep evidence boundaries as list items; never split source slashes."""
    return ('**진행 일정:**\n' + '\n'.join('- ' + line.replace('\n', '\n  ') for line in lines)
            if lines else '')


def _schedule_display_line(line: str) -> str:
    # Keep the explicit count, not the surrounding invitation. Mixed dates,
    # durations, obligations and uncertain statements retain their source text.
    plain = _plain_schedule_line(line)
    count = re.match(r'^(?:(?:단|총)\s*)*(\d+)\s*(?:번|회)', plain)
    values = schedule_values(line)
    if (count and len(values['counts']) == 1
            and not any(v for k, v in values.items() if k != 'counts')
            and not re.search(r'\d', plain[count.end():])
            and re.search(r'기회|거듭|놓치지|배워보세요', plain)
            and not re.search(r'필수|의무|신청|참가|참여|대상|자격|조건|제한|비자|거주|국적|'
                              r'보호자|동반|지참|제출|출석|참석|환불|비용|수강료|재료비|입장료|'
                              r'무료|유료|할인|면제|선착순|한정|전용|원|시간|예정|변경|취소', plain)):
        return '총 ' + str(next(iter(values['counts']))) + '회'
    return line


def schedule_lines(f: dict) -> list[str]:
    # Explicit structured sessions take precedence over the current description.
    if f.get('session_evidence'):
        return list(dict.fromkeys(_schedule_display_line(line) for line in f['session_evidence']
                                 if not _schedule_heading_or_invitation(line)))
    lines = []
    in_schedule = False
    for line in f.get('description', '').splitlines():
        line = line.strip()
        if not line:
            continue
        plain = _plain_schedule_line(line)
        if re.fullmatch(r'(?:교육|수업|강의|행사|프로그램|진행|운영)\s*(?:일정|일시)(?:\s*안내)?', plain):
            in_schedule = True
            continue
        if len(line) > 1500 or re.search(r'신청|접수|모집|발표|마감', line):
            in_schedule = False
            continue
        values = schedule_values(line)
        dated_bullet = in_schedule and re.match(_DATED_LINE, plain)
        counted_class = values['counts'] and re.search(r'총\s*\d+\s*회|\d+\s*번', line)
        labeled = re.search(r'일정|일시|회차|교육일|수업일|(?:운영|교육|수업|진행)\s*기간', line)
        if (dated_bullet or counted_class or labeled) and any(values.values()):
            line = _schedule_display_line(line)
            if line not in lines:
                lines.append(line)
        elif in_schedule and not re.match(r'(?:장소|시간)\s*[:：]', plain):
            # A different section or ordinary prose ends the date-list scope.
            in_schedule = False
    return lines


def normalize_summary_schedule(content: str, f: dict) -> str:
    """After validation, repair exact legacy serialization in the schedule section.

    No slash parsing or global replacements. Unknown/mixed prose and tables stay
    intact; only known record joins or wholly factless headings are changed.
    """
    records = f.get('session_evidence') or schedule_lines(f)
    legacy = {' / '.join(records), ' / '.join(schedule_lines(f))} - {''}
    def replace_section(match):
        lines = []
        changed = False
        for line in match[2].splitlines():
            plain = _plain_schedule_line(line)
            labeled = re.fullmatch(r'진행\s*일정\s*[:：]\s*(.*)', plain)
            if labeled and labeled[1] in legacy:
                lines.append(schedule_block(schedule_lines(f)))
                changed = True
            elif inline_text(line).strip() == '진행 일정:':
                # Retain the generated list's label on repeated processing.
                lines.append(line)
            elif not _schedule_heading_or_invitation(line):
                lines.append(line)
            else:
                changed = True
        return match[1] + '\n' + '\n'.join(lines).strip() + '\n\n' if changed else match[0]
    return re.sub(r'(?ms)(^[ \t]*\[일정 안내\][ \t]*)(.*?)(?=^[ \t]*\[|\Z)',
                  replace_section, content, count=1)


_ANNOUNCEMENT_LABEL = r'(?:합격자|선정자|당첨자|선발\s*결과|선정\s*결과|합격\s*여부|결과)\s*발표'


def _announcement_records(text: str) -> list[tuple[str, str]]:
    records = []
    for line in text.splitlines():
        plain = _plain_schedule_line(line.strip())
        match = re.match(r'^(' + _ANNOUNCEMENT_LABEL + r')\s*[:：]\s*\S', plain)
        if match and len(plain) <= 1500:
            record = (re.sub(r'\s+', '', match[1]), plain)
            if record not in records:
                records.append(record)
    return records


def announcement_lines(f: dict) -> list[str]:
    # Current reviewed description wins. No observed-source fallback or new facts.
    return [line for _, line in _announcement_records(f.get('description', ''))]


def without_replaced_announcements(content: str, f: dict) -> str:
    # Called only after validation, when the complete current source notices are
    # added to the protected block. Avoid a second AI-paraphrased copy.
    labels = {label for label, _ in _announcement_records(f.get('description', ''))}
    return '\n'.join(line for line in content.splitlines()
                     if not any(label in labels for label, _ in _announcement_records(line)))


def _validate_announcements(summary: str, f: dict) -> None:
    records = _announcement_records(f.get('description', ''))
    years = {int(e['value'][:4]) for periods in f.get('periods', {}).values()
             for period in periods if period.get('status') == 'ok'
             for e in period.get('endpoints', [])}
    for label, line in _announcement_records(summary):
        actual = _period_values(line)
        matched = False
        for source_label, source in records:
            if label != source_label:
                continue
            expected = _period_values(source)
            def compatible(a, b):
                if a == b:
                    return True
                if a[0] != 'date' or b[0] != 'date' or a[2:] != b[2:]:
                    return False
                return a[1] is None or b[1] is None and years == {a[1]}
            if len(actual) != len(expected) or not all(compatible(a, b) for a, b in zip(actual, expected)):
                continue
            _validate_dated_schedule_details(line, [source], f)
            # Don't invent a notification channel or turn individual notice into
            # public announcement. Preserve the full current source line below.
            channels = r'개별|공개|홈페이지|문자|이메일|전화'
            if set(re.findall(channels, line)) - set(re.findall(channels, source)):
                continue
            matched = True
            break
        if not matched:
            raise AiJobError('ai_schema_error')


def optional_period_section(content: str) -> str:
    content = normalize_schedule_heading(content, 'ko')
    match = re.search(r'(?ms)^\s*\[일정 안내\][ \t]*(.*?)(?=^\s*\[|\Z)', content)
    return match[1].strip() if match else ''


def retained_schedule_tables(content: str) -> str:
    """Call after schedule validation; keep original cells, not reconstructed prose.

    Only session tables in the replaced period section need rescuing. Tables in
    the activity section already survive. Reviewed period/session rows stay too.
    """
    return '\n\n'.join(table.markdown for table in schedule_tables(optional_period_section(content)))


def deduplicate_summary_venue(main: str, venue: str) -> str:
    """Remove an equal bare venue row only, retaining directions/conditions.

    No place-name inference or global replacement; mixed prose/table cells and
    different place values remain subject to the existing source checks.
    """
    if not venue:
        return main
    same = lambda value: re.sub(r'\s+', '', inline_text(value))
    kept = []
    for line in main.splitlines():
        plain = re.sub(r'^\s*[-+*]\s+', '', inline_text(line)).strip()
        match = re.fullmatch(r'(?:장소|개최 장소)\s*[:：]\s*(.+)', plain)
        if not match or same(match[1]) != same(venue):
            kept.append(line)
    return '\n'.join(kept).strip()


def _validate_session_table_rows(summary: str, f: dict) -> None:
    """Bind explicit session IDs to their own dates, clocks and labeled activities.

    The existing validator checks periods and years. This prevents values valid
    in the global number set being moved to another session. No inferred cells.
    """
    evidence = schedule_lines(f)
    identity = lambda text: re.search(r'(\d+)\s*(?:회(?:차)?|차)', inline_text(text))
    source = [(int(m[1]), line) for line in evidence if (m := identity(line))]
    source_ids = [key for key, _ in source]
    for table in schedule_tables(summary):
        headers = [inline_text(h) for h in table.headers]
        if '회차' not in headers:
            continue
        last = -1
        for row in table.rows:
            label = inline_text(row[headers.index('회차')]).strip()
            m = identity(label) or re.fullmatch(r'(\d+)', label)
            if not m or int(m[1]) not in source_ids:
                raise AiJobError('ai_schema_error')
            key = int(m[1])
            position = source_ids.index(key)
            if position <= last:
                raise AiJobError('ai_schema_error')
            last = position
            expected = [line for source_id, line in source if source_id == key]
            line = ' '.join(inline_text(cell) for cell in row)
            values = schedule_values(line)
            if not any(all(not values[k] or values[k].issubset(schedule_values(text)[k])
                           for k in ('dates', 'times', 'weekdays')) for text in expected):
                raise AiJobError('ai_schema_error')
            # Compare only an explicitly labeled source activity, not arbitrary
            # narrative semantics. The original cell is retained without repair.
            activity_columns = [i for i, h in enumerate(headers) if h in {'활동', '활동 내용'}]
            activity_evidence = expected + [text for text in f.get('description', '').splitlines()
                if (m := identity(text)) and int(m[1]) == key
                and any(schedule_values(text)['dates'] == schedule_values(item)['dates'] for item in expected)]
            activities = [m[1].strip() for text in activity_evidence
                if (m := re.search(r'(?:^|[/;])\s*활동(?: 내용)?\s*[:：]\s*(.+)$', text))]
            for index in activity_columns:
                if activities and inline_text(row[index]).strip() not in activities:
                    raise AiJobError('ai_schema_error')


def _operation_date_bounds(f: dict) -> list[tuple[date, date]]:
    bounds = []
    for period in f.get('periods', {}).get('operation', []):
        endpoints = period.get('endpoints', [])
        if period.get('status') != 'ok' or len(endpoints) != 2:
            continue
        try:
            start, end = (date.fromisoformat(endpoint['value'][:10]) for endpoint in endpoints)
        except (KeyError, TypeError, ValueError):
            continue
        if start <= end:
            bounds.append((start, end))
    return bounds


def _unique_operation_year(month: int, day: int, bounds: list[tuple[date, date]]) -> int | None:
    # Validate an existing month/day only; do not add years to facts or output.
    years = set()
    for start, end in bounds:
        for year in range(start.year, end.year + 1):
            try:
                occurrence = date(year, month, day)
            except ValueError:
                continue
            if start <= occurrence <= end:
                years.add(year)
                if len(years) > 1:
                    return None
    return next(iter(years)) if len(years) == 1 else None


def _validate_schedule_years(line: str, evidence: list[str], f: dict, expected_years: set) -> None:
    bounds = _operation_date_bounds(f)
    known_years = frozenset(year for start, end in bounds for year in range(start.year, end.year + 1))
    dates = [value for text in evidence for value in _dates_and_times(text, known_years=known_years) if value[0] == 'date']
    verified_years = set(expected_years)
    for value in _dates_and_times(line, known_years=known_years):
        if value[0] != 'date' or value[1] is None:
            continue
        _, year, month, day = value
        matches = [value for value in dates if value[2:] == (month, day)]
        if not matches:
            raise AiJobError('ai_schema_error')
        explicit = {value[1] for value in matches if value[1] is not None}
        # Explicit evidence wins. A period cannot override a conflicting year.
        allowed = explicit or {_unique_operation_year(month, day, bounds)}
        if year not in allowed:
            raise AiJobError('ai_schema_error')
        try:
            occurrence = date(year, month, day)
        except ValueError:
            raise AiJobError('ai_schema_error') from None
        if bounds and not any(start <= occurrence <= end for start, end in bounds):
            raise AiJobError('ai_schema_error')
        verified_years.add(year)
    if not schedule_values(line)['years'].issubset(verified_years):
        raise AiJobError('ai_schema_error')


def _dated_schedule_details(text: str, *, known_years: frozenset = frozenset()) -> list[tuple[tuple, set, set]]:
    # Bind explicitly adjacent weekdays/clocks to their date. Do not expand a
    # shared time, generate sessions, or treat a period endpoint as a class time.
    matches = list(re.finditer(r"\d{4}-\d{2}-\d{2}|(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일|"
                              r"(?:\d{4}|['’]\d{2})\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\.?|"
                              r"(?<![\d.])\d{1,2}\s*\.\s*\d{1,2}\.?(?=\s*[（(])", text))
    dates = [v for v in _dates_and_times(text, known_years=known_years) if v[0] == 'date']
    details = []
    for index, (match, value) in enumerate(zip(matches, dates)):
        fragment = text[match.end():matches[index+1].start() if index+1 < len(matches) else len(text)]
        weekdays = schedule_values(fragment)['weekdays']
        clocks = {v for v in _dates_and_times(fragment) if v[0] == 'time'}
        details.append((value[2:], weekdays, clocks))
    return details


def _validate_dated_schedule_details(line: str, evidence: list[str], f: dict) -> None:
    known_years = frozenset(year for start, end in _operation_date_bounds(f) for year in range(start.year, end.year + 1))
    expected = [entry for text in evidence for entry in _dated_schedule_details(text, known_years=known_years)]
    for day, weekdays, clocks in _dated_schedule_details(line, known_years=known_years):
        matches = [entry for entry in expected if entry[0] == day]
        for index, actual in ((1, weekdays), (2, clocks)):
            explicit = set().union(*(entry[index] for entry in matches))
            if explicit and not actual.issubset(explicit):
                raise AiJobError('ai_schema_error')


def _period_values(text: str) -> list[tuple]:
    return _dates_and_times(text)


def validate_summary_period(summary: str, canonical: str, f: dict) -> None:
    _validate_session_table_rows(summary, f)
    session_rows = schedule_table_lines(summary)
    summary = comparison_text(summary) + '\n' + '\n'.join(session_rows)
    canonical = comparison_text(canonical)
    _validate_announcements(summary, f)
    # Detect altered explicit ranges by role, not by a shared number bag.
    clauses = re.split(r'(?<=[.!?。])\s+|[\n;；]|(?=실제\s*수업)', summary)
    period_roles = (r'신청\s*기간',
                    r'진행\s*기간|운영\s*기간|개최\s*기간|교육\s*기간|(?:교육\s*)?운영\s*범위|교육일시\s*안내\s*범위|(?:교육|진행|프로그램)\s*일시|교육')
    for labels in period_roles:
        expected = _entry(canonical, labels)
        for clause in clauses:
            generated = _entry(_plain_schedule_line(clause), labels)
            if not generated or not expected:
                continue
            actual_values = _period_values(generated)
            expected_values = _period_values(expected)
            actual_dates = [v for v in actual_values if v[0] == 'date']
            expected_dates = [v for v in expected_values if v[0] == 'date']
            actual_clocks = [v for v in actual_values if v[0] == 'time']
            expected_clocks = [v for v in expected_values if v[0] == 'time']
            # Omitted clocks are restored by the deterministic reviewed block.
            # Any clock the model DOES state must match its own date endpoint.
            # Shared daily ranges and one-date same-day ranges keep clock order.
            one_day = len(actual_dates) == 1 and len(expected_dates) == 2 and expected_dates[0] == expected_dates[1]
            shared_daily = bool(re.search(r'각일|매일|각\s*날', generated))
            clocks_match = not actual_clocks
            if one_day or shared_daily:
                clocks_match = not actual_clocks or actual_clocks == expected_clocks
            elif actual_clocks:
                endpoint = -1
                # Each endpoint carries its own precision. A date-only start
                # and timed end are valid; never shift the end clock to start.
                expected_endpoint = -1
                endpoint_clocks = {}
                clocks_match = True
                for value in expected_values:
                    if value[0] == 'date':
                        expected_endpoint += 1
                    elif value[0] == 'time':
                        if expected_endpoint < 0 or expected_endpoint in endpoint_clocks:
                            clocks_match = False
                        endpoint_clocks[expected_endpoint] = value
                seen = set()
                for value in actual_values:
                    if value[0] == 'date':
                        endpoint += 1
                    elif value[0] == 'time':
                        if endpoint in seen or value != endpoint_clocks.get(endpoint):
                            clocks_match = False
                        seen.add(endpoint)
            if len(actual_dates) == 1 and len(expected_dates) == 2 and expected_dates[0] == expected_dates[1]:
                actual_dates *= 2
            # Omitted endpoint years are permitted here; canonical output keeps
            # the reviewed year. An explicitly different year remains a conflict.
            compatible = len(actual_dates) == len(expected_dates) and all(
                a == b or a[0] == b[0] == 'date' and a[1] is None and a[2:] == b[2:]
                for a, b in zip(actual_dates, expected_dates)) and clocks_match
            if actual_values and not compatible:
                raise AiJobError('ai_schema_error')
    evidence = schedule_lines(f) + f.get('meeting_evidence', [])
    expected = schedule_values('\n'.join(evidence))
    expected_durations = _durations('\n'.join(evidence))
    for line in clauses:
        facility_hours = False
        if 'facility_hours_evidence' in f:
            from ingest.seoul_operating_hours import validate_facility_hours_clause
            facility_hours = validate_facility_hours_clause(line, f)
        if re.search(r'신청|접수|모집|발표|마감', line):
            continue
        if (re.search(r'일정|회차|집결|실제\s*수업|총\s*\d+\s*회', line)
                or re.match(_DATED_LINE, _plain_schedule_line(line))):
            actual = schedule_values(line)
            if _durations(line).keys() - expected_durations.keys():
                raise AiJobError('ai_schema_error')
            if any(not values.issubset(expected[key]) for key, values in actual.items()
                   if key != 'years' and not (key == 'times' and facility_hours)):
                raise AiJobError('ai_schema_error')
            _validate_schedule_years(line, evidence, f, expected['years'])
            _validate_dated_schedule_details(line, evidence, f)


def _promotional_condition_candidate(value: str) -> bool:
    # The source extractor records keyword matches, not verified eligibility.
    # Keep ambiguous or mixed statements; omit only clear benefit/interest copy.
    protected = (r'신청|대상|참가|참여|수강|자격|조건|제한|불가|국적|비자|체류|거주|주민|연령|'
                 r'보호자|동반|준비물|지참|제출|출석|참석|취소|불참|환불|납부|재료비|입장료|'
                 r'비용|할인|면제|정원|인원|선착순|조기\s*마감|이상|이하|해야|하여야|있어야|없어야|'
                 r'\d+\s*(?:명|세|살|원|시간|회|급|점)')
    if re.search(protected, value):
        return False
    if re.search(r'(?:효율|생산성|역량|능력).{0,30}\d+(?:\.\d+)?\s*%.{0,30}(?:향상|강화|올|높|개선)', value):
        return not re.search(r'필수|의무', re.sub(r'실무\s*필수\s*엑셀', '', value))
    # "요즘 필수라는 ... 고민되시나요?" describes interest, not an obligation.
    # A second obligation elsewhere in the same sentence must still be kept.
    question = re.sub(r'요즘\s*필수라는', '', value)
    return bool(re.search(r'(?:나요|까요|가요)\s*[?？]\s*$', question)
                and re.search(r'고민|막막|어렵|어려|궁금|배우고\s*싶', question)
                and not re.search(r'필수|의무|가능|전용|한정|분|사람|초보|경험|수준|않|못|없|(?<!지)만\s', question))


def participation_constraints(f: dict) -> list[str]:
    candidates = [v for v in f.get('conditions', []) if not _promotional_condition_candidate(v)]
    # Typed reviewed fields retain their role even if their text resembles copy.
    values = [*candidates, *f.get('age', []), *f.get('companion', []),
              *f.get('language', []), f.get('residence', ''), f.get('qualification_note', '')]
    result = []
    for value in values:
        if value.strip() and value not in result:
            result.append(value)
    return result


def validate_participant_quantities(f: dict, main: str) -> None:
    main = comparison_text(main)
    required = _quantities('\n'.join([f['target'], *participation_constraints(f),
                                      *f.get('capacity_raw', [])]), japanese=False)
    actual = _quantities(f['target'] + '\n' + main, japanese=False)
    if required.keys() - actual.keys():
        raise AiJobError('ai_schema_error')
    # Additional quantities in generated prose must also occur in current data.
    source = '\n'.join([f.get('description', ''), f['target'],
        *participation_constraints(f), *f.get('capacity_raw', []), *schedule_lines(f)])
    if actual.keys() - _quantities(source, japanese=False).keys():
        raise AiJobError('ai_schema_error')


_FEE_VALUE = re.compile(
    r'(?P<label>수강료|입장료|재료비|기타\s*비용)\s*(?:[는은이가를을]\s*|[:：]\s*)?'
    r'(?:별도로\s*)?(?P<per_person>1인당\s*)?'
    r'(?P<value>무료|무상|\d[\d,]*(?:\.\d+)?\s*(?:만|천)?\s*(?:원|엔|円|달러|USD))')


def validate_summary_fees(main: str, activity: str) -> None:
    main, activity = comparison_text(main), comparison_text(activity)
    for label in ('수강료', '입장료', '재료비', '기타 비용'):
        generated, expected = _entry(main, label), _entry(activity, label)
        if generated is not None:
            generated = re.split(r'(?:수강료|입장료|재료비|기타\s*비용)\s*(?:[:：]|는|은)',
                generated, maxsplit=1)[0]
            if expected is None or _amounts(generated, japanese=False) != _amounts(expected, japanese=False):
                raise AiJobError('ai_schema_error')
            if bool(re.search(r'무료|무상', generated)) != bool(re.search(r'무료|무상', expected)):
                raise AiJobError('ai_schema_error')
    # Natural prose also carries a cost role; validate before removing repeats.
    for match in _FEE_VALUE.finditer(main):
        label = '기타 비용' if match['label'].startswith('기타') else match['label']
        expected = _entry(activity, label)
        value = match['value']
        if (expected is None or _amounts(value, japanese=False) != _amounts(expected, japanese=False)
                or bool(re.search(r'무료|무상', value)) != bool(re.search(r'무료|무상', expected))):
            raise AiJobError('ai_schema_error')


def _fee_sentences(text: str):
    for line in text.splitlines(keepends=True):
        yield from re.split(r'(?<=[.!?。])(?=\s|$)', line)


def _simple_fee_sentence(sentence: str) -> bool:
    text = re.sub(r'^\s*비용\s*[:：]\s*', '', comparison_text(sentence).strip())
    matches = list(_FEE_VALUE.finditer(text))
    if not matches or any(match['per_person'] for match in matches):
        return False
    # A bounded grammar for fee-only statements. Any activity, unit qualifier,
    # alternative, discount/refund/payment condition stays in the residue.
    residue = _FEE_VALUE.sub('', text)
    return re.fullmatch(
        r'[\s,;；.!?。]*(?:(?:입니다|이다|이며|이고|및|와|과|이|가|는|은|별도로|별도|있습니다|있다)'
        r'[\s,;；.!?。]*)*', residue) is not None


def deduplicate_summary_fees(main: str, activity: str) -> str:
    """Keep authoritative fee rows, removing only equivalent fee-only prose.

    Mixed activity/discount/refund sentences stay intact. Reviewed fee rows keep
    all their qualifiers. No inferred totals or changes to reviewed facts.
    """
    validate_summary_fees(main, activity)
    return ''.join(sentence for sentence in _fee_sentences(main)
                   if '|' in sentence or not _simple_fee_sentence(sentence)).strip()


def validate_assembled_fees(content: str, activity: str, *, canonical_block: str | None = None) -> None:
    """Exclude the one reviewed block; reject recognizable leftover simple fees.

    This checks all public sections, including a fee-only summary. Conditions
    that cannot be separated safely are preserved, not classified as duplicates.
    """
    block = canonical_block if canonical_block is not None else activity
    if block and content.count(block) != 1:
        raise AiJobError('ai_schema_error')
    # Empty reviewed fees have no public fee row. Validate the entire text;
    # never invent a free/paid value or bypass the existing component checks.
    generated = content.replace(block, '', 1) if block else content
    validate_summary_fees(generated, activity)
    # Never remove table cells. A pure repeat fails before translation; a row
    # containing an inseparable refund/discount/activity condition stays intact.
    table_rows = []
    for table in read_body(generated).tables:
        for row in table.rows:
            first = inline_text(row[0])
            if re.fullmatch(r'수강료|입장료|재료비|기타\s*비용', first):
                table_rows.append(first + ': ' + '; '.join(inline_text(c) for c in row[1:]))
            else:
                table_rows.append('; '.join(inline_text(h) + ': ' + inline_text(c)
                    for h, c in zip(table.headers, row)))
    if any(_simple_fee_sentence(sentence) for sentence in [
            *[s for s in _fee_sentences(generated) if '|' not in s], *table_rows]):
        raise AiJobError('ai_schema_error')
