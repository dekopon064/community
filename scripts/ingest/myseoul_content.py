"""Bounded checks for explicit reviewed quantities and schedule lines.

No model calls, calendar expansion, source lookup or inferred sessions.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from ingest.ai_errors import AiJobError
from ingest.body_sections import normalize_schedule_heading
from ingest.myseoul_ai_support import schedule_values
from ingest.translation_validation import _dates_and_times, _entry, _quantities, _amounts

_DATED_LINE = (r'^(?:제?\d+\s*(?:회차|차)\s*[:.)-]?\s*)?'
               r'(?:(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}-\d{2}-\d{2})')


def _plain_schedule_line(line: str) -> str:
    return re.sub(r'^[^\w가-힣\[]+', '', line).strip('[]:： ')


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
        return list(dict.fromkeys(_schedule_display_line(line) for line in f['session_evidence']))
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
        labeled = re.search(r'일정|일시|회차|교육일|수업일', line)
        if (dated_bullet or counted_class or labeled) and any(values.values()):
            line = _schedule_display_line(line)
            if line not in lines:
                lines.append(line)
        elif in_schedule and not re.match(r'(?:장소|시간)\s*[:：]', plain):
            # A different section or ordinary prose ends the date-list scope.
            in_schedule = False
    return lines


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
            _validate_dated_schedule_details(line, [source])
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
    dates = [value for text in evidence for value in _dates_and_times(text) if value[0] == 'date']
    bounds = _operation_date_bounds(f)
    verified_years = set(expected_years)
    for value in _dates_and_times(line):
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


def _dated_schedule_details(text: str) -> list[tuple[tuple, set, set]]:
    # Bind explicitly adjacent weekdays/clocks to their date. Do not expand a
    # shared time, generate sessions, or treat a period endpoint as a class time.
    matches = list(re.finditer(r'\d{4}-\d{2}-\d{2}|(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일', text))
    dates = [v for v in _dates_and_times(text) if v[0] == 'date']
    details = []
    for index, (match, value) in enumerate(zip(matches, dates)):
        fragment = text[match.end():matches[index+1].start() if index+1 < len(matches) else len(text)]
        weekdays = schedule_values(fragment)['weekdays']
        clocks = {v for v in _dates_and_times(fragment) if v[0] == 'time'}
        details.append((value[2:], weekdays, clocks))
    return details


def _validate_dated_schedule_details(line: str, evidence: list[str]) -> None:
    expected = [entry for text in evidence for entry in _dated_schedule_details(text)]
    for day, weekdays, clocks in _dated_schedule_details(line):
        matches = [entry for entry in expected if entry[0] == day]
        for index, actual in ((1, weekdays), (2, clocks)):
            explicit = set().union(*(entry[index] for entry in matches))
            if explicit and not actual.issubset(explicit):
                raise AiJobError('ai_schema_error')


def _period_values(text: str) -> list[tuple]:
    # Raw reclassification filters retain ISO offsets. Compare their local KST
    # date/time, without misreading '+09:00' as a third clock in the range.
    def local_time(match):
        try:
            value = datetime.fromisoformat(match[0].replace('Z', '+00:00'))
        except ValueError:
            raise AiJobError('ai_schema_error') from None
        return value.astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None).isoformat()
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})', local_time, text)
    return _dates_and_times(normalized)


def validate_summary_period(summary: str, canonical: str, f: dict) -> None:
    _validate_announcements(summary, f)
    # Detect altered explicit ranges by role, not by a shared number bag.
    clauses = re.split(r'(?<=[.!?。])\s+|[\n;；]|(?=실제\s*수업)', summary)
    period_roles = (r'신청\s*기간',
                    r'진행\s*기간|운영\s*기간|개최\s*기간|교육\s*기간|(?:교육\s*)?운영\s*범위')
    for labels in period_roles:
        expected = _entry(canonical, labels)
        for clause in clauses:
            generated = _entry(clause, labels)
            if not generated or not expected:
                continue
            actual_values = _period_values(generated)
            expected_values = _period_values(expected)
            # Omitted endpoint years are permitted here; canonical output keeps
            # the reviewed year. An explicitly different year remains a conflict.
            compatible = len(actual_values) == len(expected_values) and all(
                a == b or a[0] == b[0] == 'date' and a[1] is None and a[2:] == b[2:]
                for a, b in zip(actual_values, expected_values))
            if actual_values and not compatible:
                raise AiJobError('ai_schema_error')
    evidence = schedule_lines(f) + f.get('meeting_evidence', [])
    expected = schedule_values('\n'.join(evidence))
    for line in clauses:
        if re.search(r'신청|접수|모집|발표|마감', line):
            continue
        if (re.search(r'일정|회차|집결|실제\s*수업|총\s*\d+\s*회', line)
                or re.match(_DATED_LINE, _plain_schedule_line(line))):
            actual = schedule_values(line)
            if any(not values.issubset(expected[key]) for key, values in actual.items() if key != 'years'):
                raise AiJobError('ai_schema_error')
            _validate_schedule_years(line, evidence, f, expected['years'])
            _validate_dated_schedule_details(line, evidence)


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
    text = re.sub(r'^\s*비용\s*[:：]\s*', '', sentence.strip())
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
                   if not _simple_fee_sentence(sentence)).strip()


def validate_assembled_fees(content: str, activity: str, *, canonical_block: str | None = None) -> None:
    """Exclude the one reviewed block; reject recognizable leftover simple fees.

    This checks all public sections, including a fee-only summary. Conditions
    that cannot be separated safely are preserved, not classified as duplicates.
    """
    block = canonical_block if canonical_block is not None else activity
    if content.count(block) != 1:
        raise AiJobError('ai_schema_error')
    generated = content.replace(block, '', 1)
    validate_summary_fees(generated, activity)
    if any(_simple_fee_sentence(sentence) for sentence in _fee_sentences(generated)):
        raise AiJobError('ai_schema_error')
