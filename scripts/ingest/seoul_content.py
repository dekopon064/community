"""Public body projection of the existing Seoul facts contract.

No source lookup, geography inference or DB facts mutation. Shared MySeoul
validators receive an ephemeral view, never a replacement stored schema.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone, timedelta
from ingest.ai_errors import ValidationError, validation_location
from ingest.ai_worker import KO_SECTION_HEADERS
from ingest.body_markdown import format_reviewed_block, schedule_tables, read_body, schedule_table_lines, inline_text
from ingest.seoul_common_timetable import common_timetable, source_schedule, timetable_validation_input
from ingest.myseoul_ai_support import section_body
from ingest.seoul_fact_roles import (public_roles, weekly_schedule, validate_weekly_schedule,
                                   booking_covered, clean_role_repetitions, optional_section, plain, key)
from ingest.myseoul_content import (
    announcement_lines, deduplicate_summary_fees, merge_reviewed_sections,
    normalize_summary_schedule, participation_constraints, schedule_block,
    schedule_lines, validate_assembled_fees, validate_participant_quantities,
    validate_summary_period, without_replaced_announcements,
    _operation_date_bounds, _unique_operation_year,
)

KST = timezone(timedelta(hours=9))
PAIRS = {'application': ('RCPTBGNDT', 'RCPTENDDT'),
         'operation': ('SVCOPNBGNDT', 'SVCOPNENDDT')}


def validate_public_body(content: str) -> None:
    read_body(content)
    if re.search(r'(?im)^\s*(?:참고\s*[:：]\s*)?(?:JSON\s*(?:출력|응답|형식|出力|形式|output|response)|출력은\s*JSON|검수\s*평가|수정\s*이유)\s*[:：]', content):
        raise ValidationError('public_body', 'internal_instruction')


def public_date(endpoint: dict) -> str:
    value = endpoint['value']
    if endpoint['precision'] == 'day':
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValidationError('reviewed_datetime', 'missing_timezone')
    parsed = parsed.astimezone(KST)
    return parsed.strftime('%Y-%m-%d %H:%M:%S' if parsed.second else '%Y-%m-%d %H:%M')


def period_text(facts: dict, role: str) -> str:
    return ' ~ '.join(public_date(facts['periods'][key]) for key in PAIRS[role])


def _recruitment_session_lines(view: dict) -> list[str]:
    """Seoul sometimes labels class dates '모집 일시', not reception dates.

    Require listed dates with clock ranges anchored to the verified operation
    endpoints. Do not expand a date range, interpret a recruitment period or
    relabel an ambiguous date inside both application and operation periods.
    Split only an explicit shared-month day list for comparison; keep the
    original description and every original time/separator untouched.
    """
    bounds = _operation_date_bounds(view)
    result = []
    for line in view['description'].splitlines():
        plain = re.sub(r'^[^\w가-힣]+', '', inline_text(line)).strip()
        match = re.fullmatch(r'모집\s*일시\s*[:：]\s*'
            r'(?:(?P<year>\d{4})\s*년\s*)?(?P<month>\d{1,2})\s*월\s*'
            r'(?P<days>(?:\d{1,2}\s*일?\s*[,·、・]\s*)*\d{1,2}\s*일)(?P<tail>.*)', plain)
        if not match or len(line) > 1500:
            continue
        tail = match['tail']
        # The list must end here, not at the first endpoint of a range or at
        # another date with independently bound times. Such text stays data.
        if (re.search(r'신청|접수|모집|발표|마감|\d+\s*[월일]|\d{4}-\d{2}-\d{2}', tail)
                or re.match(r'\s*(?:~|～|〜|부터|까지|[-–—])', tail)):
            continue
        clock = r'(?:\d{1,2}:[0-5]\d|\d{1,2}\s*시(?:\s*[0-5]?\d\s*분)?)'
        remainder, ranges = re.subn(rf'{clock}\s*(?:~|～|〜|–|—|-|부터)\s*{clock}', '', tail)
        remainder = re.sub(r'[（(]\s*[월화수목금토일](?:요일)?\s*[）)]|오전|오후', '', remainder)
        if not ranges or remainder.strip(' \t/,·、・;；'):
            # Mixed prose/activities or independently bound dates require
            # existing explicit schedule evidence, not guesses from this label.
            continue
        month = int(match['month'])
        days = [int(v) for v in re.findall(r'\d+', match['days'])]
        occurrences = []
        for day in days:
            year = int(match['year']) if match['year'] else _unique_operation_year(month, day, bounds)
            try:
                occurrences.append(date(year, month, day))
            except (TypeError, ValueError):
                break
        else:
            if not any(min(occurrences) == start and max(occurrences) == end
                       and all(start <= value <= end for value in occurrences) for start, end in bounds):
                continue
            if len(set(occurrences)) == 1:
                application = view['periods'].get('application', [])
                # One timestamp during the application period is ambiguous.
                # A one-day class is supported only after registration ends.
                try:
                    end = date.fromisoformat(application[0]['endpoints'][1]['value'][:10])
                except (IndexError, KeyError, TypeError, ValueError):
                    continue
                if end >= occurrences[0]:
                    continue
            prefix = match['year'] + '년 ' if match['year'] else ''
            result += [f'{prefix}{month}월 {day}일{tail}' for day in days]
    return list(dict.fromkeys(result))


def source_description(text: str) -> str:
    """Drop embedded players/scripts from the source projection only."""
    return re.sub(r'<(iframe|script)\b[^>]*>.*?</\1\s*>', '', text, flags=re.I | re.S)


def validation_view(facts: dict) -> dict:
    from ingest.seoul_operating_hours import facility_hours_evidence
    description = source_description(facts['description'])
    facts = {**facts, 'description': description}
    # Only explicitly labelled capacity text; V_MIN/V_MAX have no known role.
    roles = public_roles(facts)
    from ingest.seoul_fact_roles import capacity_text, viewing_hours
    capacity = list(dict.fromkeys([*(plain(line) for line in roles['capacity']),
                                   *(plain(line) for line in description.splitlines() if capacity_text(line))]))
    sessions = schedule_table_lines(description)
    view = {'target': facts['target_raw'], 'description': description,
            'conditions': roles['eligibility'], 'capacity_raw': capacity,
            'viewing_hours': [value for _, value in viewing_hours(description)],
            'facility_hours_evidence': facility_hours_evidence(description),
            **({'session_evidence': sessions} if sessions else {}),
            'periods': {role: [{'status': 'ok', 'endpoints': [facts['periods'][k] for k in pair]}]
                        for role, pair in PAIRS.items()}}
    from ingest.seoul_condition_layout import condition_signature
    view['schedule_notice_signatures'] = [sig for v in roles['schedule'] if
                                          (sig := condition_signature(v)) and sig[0] == 'session_no_participants']
    recruitment = _recruitment_session_lines(view)
    if recruitment:
        # Retain existing tables/ordinary schedules as well as this narrowly
        # supported source label. The shared MySeoul extraction is unchanged.
        view['session_evidence'] = list(dict.fromkeys(schedule_lines(view) + recruitment))
    # In an explicit operating-day section, “체험 ... 신청 가능” can
    # describe the days offered, independent of the reservation window.
    operating = False
    operating_days = []
    for line in description.splitlines():
        if re.search(r'\[\s*운영일\s*안내\s*\]', line):
            operating = True
            continue
        if operating and re.search(r'매주\s+[월화수목금토일,·\s]+요일\s+체험\s*프로그램\s*신청\s*가능', line):
            days = re.search(r'매주\s+([월화수목금토일,·\s]+)요일', line)[1]
            operating_days.append('체험 가능 요일: ' + ', '.join(ch + '요일' for ch in days if ch in '월화수목금토일'))
            operating = False
        elif operating and re.match(r'\s*(?:\[|[0-9]+\.)', line):
            operating = False
    if operating_days:
        view['operating_day_evidence'] = operating_days
    matrix = weekly_schedule(description)
    if matrix:
        # Separate validation evidence from public rendering: bare table cells
        # are never independently appended as sessions or participation rules.
        table_rows = {key('| '+' | '.join(row)+' |') for row in matrix.rows}
        annotated_cells = {key(plain(cell)) for row in matrix.rows for cell in row[1:]
                           if re.fullmatch(r'(?:제\s*)?\d+\s*회차\s*[（(][^()（）]+[）)]', plain(cell))}
        records = [line for line in schedule_lines(view)
                   if key(plain(line)) not in annotated_cells and not re.fullmatch(r'(?:제\s*)?\d+\s*회차', plain(line))
                   and key(plain(line)) not in table_rows]
        matrix_records = ['해설회차: ' + ' '.join(row) for row in matrix.rows]
        view['session_evidence'] = list(dict.fromkeys(records + roles['schedule'] + matrix_records))
        view['weekly_validation_records'] = matrix_records
        view['weekly_schedule'] = matrix
    return view


def reception_status(facts: dict, now: datetime | None = None) -> str:
    now = (now or datetime.now(KST)).astimezone(KST)
    def boundary(key, end=False):
        endpoint = facts['periods'][key]
        value = datetime.fromisoformat(endpoint['value'])
        if endpoint['precision'] == 'day':
            value = value.replace(tzinfo=KST)
            if end:
                value += timedelta(days=1)
        return value.astimezone(KST)
    def ended(key):
        end = boundary(key, True)
        return now >= end if facts['periods'][key]['precision'] == 'day' else now > end
    if ended('SVCOPNENDDT'):
        return '운영 종료'
    if facts['source_status'] in {'reservation_closed', 'application_closed'}:
        return {'reservation_closed': '예약 마감', 'application_closed': '접수 종료'}[facts['source_status']]
    if now < boundary('RCPTBGNDT'):
        return '접수 전' if facts['source_status'] == 'announced' else '신청 시작 전'
    if ended('RCPTENDDT'):
        return '접수 마감'
    if facts['source_status'] == 'announced':
        return '접수 전'
    return '접수 중'


def public_audience(facts, constraints):
    """Combine a matching age floor and an explicit interest-based audience.

    Keep different ages, additional qualifiers and operator overrides visible.
    Residence evidence is a quote from the audience, not a residence decision.
    """
    raw = facts['target_raw']
    age = re.fullmatch(r'제한\s*없음\s*\(\s*(\d+)\s*세\s*이상\s*\)', raw.strip())
    labels = {}
    for value in constraints:
        match = re.fullmatch(r'(?:참가\s*)?대상\s*[:：]\s*(.+)', value)
        if match:
            labels[value] = match[1]
    audience = '대상: ' + raw
    covered = {key(raw)}
    if age and len(labels) == 1:
        phrase = next(iter(labels.values()))
        detail = re.fullmatch(r'([가-힣· ]+에)\s*관심\s*있는\s*일반\s*시민\s*'
                              r'\(\s*(\d+)\s*세\s*이상\s*\)', phrase)
        if detail and detail[2] == age[1]:
            audience = f'{detail[1]} 관심 있는 {age[1]}세 이상이면 참여할 수 있습니다.'
            covered.add(key(phrase))
    rows = [audience]
    for value in constraints:
        phrase = labels.get(value, value)
        if key(phrase) not in covered:
            rows.append(('대상: ' if value in labels else '참가 조건: ') + phrase)
            covered.add(key(phrase))
    from ingest.program_scope import TARGET_LABELS
    from ingest.seoul_evidence import label_values
    stated = {key(v) for v in label_values(facts['description'], TARGET_LABELS)} if facts['residence_evidence'] else set()
    for quote in facts['residence_evidence']:
        if key(quote) not in covered and (key(quote) in stated or
                re.search(r'거주(?:자|민|지|하고|하는)|주민등록|전국|지역\s*제한\s*없|'
                          r'[가-힣]+(?:구민|시민|군민|도민|주민)(?:만|에\s*한|을?\s*우선|\s*대상)', quote)):
            # The stored quote stays available for review. Only an actual
            # audience rule belongs in public prose, with its qualifiers.
            rows.append('대상: ' + quote)
            covered.add(key(quote))
    return rows


def reviewed_sections(facts: dict, *, now: datetime | None = None) -> dict[str, str]:
    view = validation_view(facts)
    roles = public_roles(facts)
    target = public_audience(facts, participation_constraints(view))
    from ingest.seoul_fact_roles import capacity_text, is_booking_capacity
    booking_capacity = []
    for value in view['capacity_raw']:
        # Keep standalone capacity under its existing neutral label. Channel
        # quotas and reservation limits describe how to book.
        row = capacity_text(value) or plain(value)
        if is_booking_capacity(value):
            row = re.sub(r'^(회(?:차)?당)\s*예약\s*인원\s+(?=최대\s*\d+\s*명)', r'\1 ', row)
            booking_capacity.append('예약 인원: ' + row)
        else:
            target.append('모집 인원: ' + row)
    dates = ['신청기간: ' + period_text(facts, 'application'),
             '진행기간: ' + period_text(facts, 'operation')]
    sessions = schedule_block([line for line in schedule_lines(view)
                               if line not in view.get('weekly_validation_records', [])])
    if sessions:
        dates.append('\n' + sessions)
    from ingest.seoul_condition_display import additional_role
    tables = schedule_tables(view['description'])
    # A copied source table replaces the ordinary schedule block below. Other
    # source rows may carry exceptions outside that table and must survive.
    session_rows = set() if tables else {key(plain(line)) for line in schedule_lines(view)}
    for value in roles['schedule']:
        if additional_role(value) == 'schedule' and key(plain(value)) not in session_rows:
            dates.append('진행 일정: ' + plain(value))
    # Explicit table cells come from current description, not an old observed
    # HTML snapshot. Copy only the already parsed supported schedule tables.
    if tables:
        dates = [line for line in dates if line != '\n' + sessions]
        dates += ['\n' + table.markdown for table in tables]
    dates += announcement_lines(view)
    dates.extend(view['viewing_hours'])
    activity = ['진행 방식: ' + {'online': '온라인', 'offline': '오프라인', 'hybrid': '온·오프라인 혼합'}[facts['delivery_mode']]]
    activity += ['- **이용 안내:** ' + plain(value) for value in roles['activity']]
    if facts['activity_evidence']:
        activity += ['장소: ' + value for value in facts['activity_evidence']]
    # Do not rename unlabeled amounts to tuition/materials or infer totals.
    if facts['fee_amounts']:
        activity.append('비용: ' + '; '.join(facts['fee_amounts']))
    elif facts['fee_kind'] == 'free':
        activity.append('비용: 무료')
    else:
        activity.append('비용: ' + {'paid': '유료 · 금액은 공식 안내 확인', 'unknown': '공식 안내 확인'}[facts['fee_kind']])
    methods = [dict(internet='인터넷 예약', onsite='현장 접수', phone='전화 신청')[v]
               for v in facts['application_methods']]
    method = ['신청 방법: ' + ' / '.join(methods)] if methods else []
    method.extend(booking_capacity)
    if facts['application_actor'] == 'individual_or_group':
        method.append('신청 주체: 개인 또는 단체')
    return {header: format_reviewed_block('\n'.join(lines)) for header, lines in (
        ('[대상]', target), ('[일정 안내]', dates), ('[주요 내용]', activity), ('[신청 방법]', method))}


def assemble_seoul_body(content: str, facts: dict, *, reviewed: dict | None = None, periods: dict | None = None, review=None) -> str:
    from ingest.body_sections import normalize_schedule_heading
    from ingest.seoul_public_guidance import without_reception_status, ensure_application_guidance, validate_public_guidance
    from ingest.seoul_schedule_display import normalize_period_labels, clean_schedule_display, validate_checkin
    facts = {**facts, 'description': source_description(facts['description'])}
    content = normalize_period_labels(normalize_schedule_heading(content, 'ko'))
    view = validation_view(facts)
    # Reclassification supplies its current reviewed date roles without
    # mutating the source facts or discarding original session evidence.
    if periods:
        view['periods']={**view['periods'],**periods}
    # Display relocation must not reduce the old numeric validation evidence.
    # In particular booking limits and deadline consequences remain checked.
    from ingest.seoul_condition_display import projected_conditions
    quantity_view = {**view, 'conditions': list(dict.fromkeys([
        *view['conditions'], *projected_conditions(facts)]))}
    sections = {h: without_reception_status(value) for h, value in (reviewed or reviewed_sections(facts)).items()}
    canonical = '\n'.join(sections.values())
    # A model-contract explanation is not a program instruction. Reject only
    # recognized standalone output directives; a class teaching JSON stays data.
    validate_public_body(content)
    def strict(validate, *args, **kwargs):
        validate(*args, **kwargs)

    check = review.check if review else strict
    def clean(transform, *args, fallback, rules):
        # Cleanup must not turn an advisory content finding into a terminal
        # failure. Keep the entire pre-cleanup text when equivalence cannot be
        # proved. Structural errors and unexpected failures remain terminal.
        try:
            with validation_location(field='content_ko'):
                return transform(*args)
        except ValidationError as error:
            if (review is None or error.diagnostic['rule'] not in rules
                    or getattr(error, 'failure_scope', None) == 'batch'):
                raise
            review.record(error)
            return fallback
    check(validate_weekly_schedule, content, facts['description'])
    from ingest.seoul_calendar_sessions import validate_calendar_sessions, dated_slot_evidence
    common = source_schedule(view, facts['conditions'])
    calendar_input, period_view = timetable_validation_input(content, dated_slot_evidence(view), common)
    check(validate_calendar_sessions, calendar_input, period_view)
    # These same checks run before cleanup, so conflicting AI facts cannot be
    # hidden by removal/replacement of a generated row.
    check(validate_summary_period, calendar_input, canonical, period_view)
    check(validate_checkin, content, view)
    check(validate_participant_quantities, view, content+'\n'+canonical)
    content = without_reception_status(content)
    content, sections = clean(clean_schedule_display, content, sections, view,
                              fallback=(content, sections), rules={'clock'})
    content = clean(normalize_summary_schedule, content, view,
                    fallback=content, rules={'clock'})
    content = without_replaced_announcements(content, view)
    main = section_body(content, '[주요 내용]', KO_SECTION_HEADERS)
    fee_block = '\n'.join(line for line in sections['[주요 내용]'].splitlines()
                          if re.search(r'\*\*비용:', line))
    main = clean(deduplicate_summary_fees, main, fee_block,
                 fallback=main, rules={'reviewed_fee'})
    boundary = '|'.join(re.escape(h) for h in KO_SECTION_HEADERS)
    content = re.sub(r'(?ms)(^\s*\[주요 내용\][ \t]*)(.*?)(?=^\s*(?:'+boundary+r')|\Z)',
                     lambda match: match[1]+'\n'+(main or '공식 안내의 프로그램 내용')+'\n', content, count=1)
    from ingest.seoul_body_display import clean_fact_repetitions
    content, sections = clean_fact_repetitions(content, sections, facts)
    content, sections = clean_role_repetitions(content, sections, facts)
    from ingest.seoul_condition_display import clean_projected_duplicates, additional_role, covered_condition
    from ingest.seoul_condition_display import reservation_clauses, reservation_evidence
    from ingest.seoul_condition_layout import cancellation_covers, cancellation_steps
    content, sections = clean_projected_duplicates(content, sections, facts)
    method = optional_section(content, '[신청 방법]')
    sections = dict(sections)
    bookings = public_roles(facts)['booking']
    cancellations = [v for v in bookings if cancellation_steps(v)]
    cancellation_proof = method.splitlines()
    booking_proof = reservation_evidence(method, sections['[주요 내용]'])
    for value in bookings:
        steps = cancellation_steps(value)
        if steps:
            if (not any(cancellation_covers(v, value) and not cancellation_covers(value, v)
                                for v in cancellations)
                    and not any(cancellation_covers(line, value) for line in cancellation_proof)):
                sections['[신청 방법]'] += '\n- **취소 방법:** ' + steps
                cancellation_proof.append(value)
            continue
        clauses = reservation_clauses(value)
        if clauses:
            missing = [clause for clause in clauses if clause not in booking_proof]
            if not missing:
                continue
            booking_proof.update(missing)
            if len(missing) < len(clauses):
                for clause in missing:
                    sections['[신청 방법]'] += '\n- **예약 절차:** ' + clause
                continue
        elif covered_condition(value, method) or (not additional_role(value) and booking_covered(value, method)):
            continue
        sections['[신청 방법]'] += '\n- **예약 절차:** ' + plain(value)
    content = merge_reviewed_sections(content, sections)
    content = common_timetable(content, common)
    content = ensure_application_guidance(content, facts)
    check(validate_public_guidance, content, 'ko')
    check(validate_participant_quantities, quantity_view, content)
    check(validate_assembled_fees, content, fee_block, canonical_block=fee_block)
    check(validate_weekly_schedule, content, facts['description'])
    # Source tables are evidence. They are not blindly copied, but every
    # generated table is validated above before a candidate can be created.
    if schedule_tables(facts['description']) and not schedule_tables(content):
        error = ValidationError('schedule_table', 'missing')
        if review is None:
            raise error
        review.record(error)
    return content
