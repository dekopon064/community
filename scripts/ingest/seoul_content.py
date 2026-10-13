"""Public body projection of the existing Seoul facts contract.

No source lookup, geography inference or DB facts mutation. Shared MySeoul
validators receive an ephemeral view, never a replacement stored schema.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone, timedelta
from ingest.ai_errors import AiJobError
from ingest.ai_worker import KO_SECTION_HEADERS
from ingest.body_markdown import format_reviewed_block, schedule_tables, read_body, schedule_table_lines, inline_text
from ingest.myseoul_ai_support import section_body
from ingest.seoul_fact_roles import (public_roles, weekly_schedule, validate_weekly_schedule,
                                   booking_covered, clean_role_repetitions, optional_section, plain)
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
        raise AiJobError('ai_schema_error')


def public_date(endpoint: dict) -> str:
    value = endpoint['value']
    if endpoint['precision'] == 'day':
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise AiJobError('ai_schema_error')
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


def validation_view(facts: dict) -> dict:
    description = facts['description']
    # Only explicitly labelled capacity text; V_MIN/V_MAX have no known role.
    roles = public_roles(facts)
    capacity = list(dict.fromkeys(roles['capacity'] + [line.strip() for line in description.splitlines()
                if re.match(r'^(?:모집\s*인원|참가\s*인원|인원|정원)\s*[:：]', plain(line))]))
    sessions = schedule_table_lines(description)
    view = {'target': facts['target_raw'], 'description': description,
            'conditions': roles['eligibility'], 'capacity_raw': capacity,
            **({'session_evidence': sessions} if sessions else {}),
            'periods': {role: [{'status': 'ok', 'endpoints': [facts['periods'][k] for k in pair]}]
                        for role, pair in PAIRS.items()}}
    recruitment = _recruitment_session_lines(view)
    if recruitment:
        # Retain existing tables/ordinary schedules as well as this narrowly
        # supported source label. The shared MySeoul extraction is unchanged.
        view['session_evidence'] = list(dict.fromkeys(schedule_lines(view) + recruitment))
    matrix = weekly_schedule(description)
    if matrix:
        # Separate validation evidence from public rendering: bare table cells
        # are never independently appended as sessions or participation rules.
        records = [line for line in schedule_lines(view)
                   if not re.fullmatch(r'(?:제\s*)?\d+\s*회차', plain(line))]
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
        return '신청 시작 전'
    if ended('RCPTENDDT'):
        return '접수 마감'
    return '접수 중'


def reviewed_sections(facts: dict, *, now: datetime | None = None) -> dict[str, str]:
    view = validation_view(facts)
    target = ['대상: ' + facts['target_raw']]
    target += ['참가 조건: ' + value for value in participation_constraints(view)]
    target += ['거주 조건 근거: ' + value for value in facts['residence_evidence']]
    target += ['모집 인원: ' + re.sub(r'^(?:모집\s*인원|참가\s*인원|인원|정원)\s*[:：]\s*', '', plain(v))
               for v in view['capacity_raw']]
    dates = ['신청기간: ' + period_text(facts, 'application'),
             '진행기간: ' + period_text(facts, 'operation'),
             '접수 상태: ' + reception_status(facts, now)]
    sessions = schedule_block([line for line in schedule_lines(view)
                               if line not in view.get('weekly_validation_records', [])])
    if sessions:
        dates.append('\n' + sessions)
    # Explicit table cells come from current description, not an old observed
    # HTML snapshot. Copy only the already parsed supported schedule tables.
    tables = schedule_tables(facts['description'])
    if tables:
        dates = [line for line in dates if line != '\n' + sessions]
        dates += ['\n' + table.markdown for table in tables]
    dates += announcement_lines(view)
    activity = ['진행 방식: ' + {'online': '온라인', 'offline': '오프라인', 'hybrid': '온·오프라인 혼합'}[facts['delivery_mode']]]
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
    if facts['application_actor'] == 'individual_or_group':
        method.append('신청 주체: 개인 또는 단체')
    return {header: format_reviewed_block('\n'.join(lines)) for header, lines in (
        ('[대상]', target), ('[일정 안내]', dates), ('[주요 내용]', activity), ('[신청 방법]', method))}


def assemble_seoul_body(content: str, facts: dict, *, reviewed: dict | None = None, periods: dict | None = None) -> str:
    from ingest.body_sections import normalize_schedule_heading
    from ingest.seoul_schedule_display import normalize_period_labels, clean_schedule_display, validate_checkin
    content = normalize_period_labels(normalize_schedule_heading(content, 'ko'))
    view = validation_view(facts)
    # Reclassification supplies its current reviewed date roles without
    # mutating the source facts or discarding original session evidence.
    if periods:
        view['periods']={**view['periods'],**periods}
    sections = reviewed or reviewed_sections(facts)
    canonical = '\n'.join(sections.values())
    # A model-contract explanation is not a program instruction. Reject only
    # recognized standalone output directives; a class teaching JSON stays data.
    validate_public_body(content)
    validate_weekly_schedule(content, facts['description'])
    # These same checks run before cleanup, so conflicting AI facts cannot be
    # hidden by removal/replacement of a generated row.
    validate_summary_period(content, canonical, view)
    validate_checkin(content, view)
    validate_participant_quantities(view, content+'\n'+canonical)
    content, sections = clean_schedule_display(content, sections, view)
    content = normalize_summary_schedule(content, view)
    content = without_replaced_announcements(content, view)
    main = section_body(content, '[주요 내용]', KO_SECTION_HEADERS)
    fee_block = '\n'.join(line for line in sections['[주요 내용]'].splitlines()
                          if re.search(r'\*\*비용:', line))
    main = deduplicate_summary_fees(main, fee_block)
    boundary = '|'.join(re.escape(h) for h in KO_SECTION_HEADERS)
    content = re.sub(r'(?ms)(^\s*\[주요 내용\][ \t]*)(.*?)(?=^\s*(?:'+boundary+r')|\Z)',
                     lambda match: match[1]+'\n'+(main or '공식 안내의 프로그램 내용')+'\n', content, count=1)
    from ingest.seoul_body_display import clean_fact_repetitions
    content, sections = clean_fact_repetitions(content, sections, facts)
    content, sections = clean_role_repetitions(content, sections, facts)
    # Booking procedures were historically extracted as eligibility. Keep them
    # in the method section unless the generated method proves their explicit
    # search/selection tokens; never discard unique numbers/URLs/restrictions.
    method = optional_section(content, '[신청 방법]')
    sections = dict(sections)
    for value in public_roles(facts)['booking']:
        if not booking_covered(value, method):
            sections['[신청 방법]'] += '\n- **예약 절차:** ' + plain(value)
    content = merge_reviewed_sections(content, sections)
    validate_participant_quantities(view, content)
    validate_assembled_fees(content, fee_block, canonical_block=fee_block)
    validate_weekly_schedule(content, facts['description'])
    # Source tables are evidence. They are not blindly copied, but every
    # generated table is validated above before a candidate can be created.
    if schedule_tables(facts['description']) and not schedule_tables(content):
        raise AiJobError('ai_schema_error')
    return content
