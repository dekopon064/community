"""Public body projection of the existing Seoul facts contract.

No source lookup, geography inference or DB facts mutation. Shared MySeoul
validators receive an ephemeral view, never a replacement stored schema.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from ingest.ai_errors import AiJobError
from ingest.ai_worker import KO_SECTION_HEADERS
from ingest.body_markdown import format_reviewed_block, schedule_tables, read_body, schedule_table_lines
from ingest.myseoul_ai_support import section_body
from ingest.myseoul_content import (
    announcement_lines, deduplicate_summary_fees, merge_reviewed_sections,
    normalize_summary_schedule, participation_constraints, schedule_block,
    schedule_lines, validate_assembled_fees, validate_participant_quantities,
    validate_summary_period, without_replaced_announcements,
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


def validation_view(facts: dict) -> dict:
    description = facts['description']
    # Only explicitly labelled capacity text; V_MIN/V_MAX have no known role.
    capacity = [line.strip() for line in description.splitlines()
                if re.match(r'^\s*(?:[-*■]\s*)?(?:모집\s*인원|정원)\s*[:：]', line)]
    sessions = schedule_table_lines(description)
    return {'target': facts['target_raw'], 'description': description,
            'conditions': facts['conditions'], 'capacity_raw': capacity,
            **({'session_evidence': sessions} if sessions else {}),
            'periods': {role: [{'status': 'ok', 'endpoints': [facts['periods'][k] for k in pair]}]
                        for role, pair in PAIRS.items()}}


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
    target += view['capacity_raw']
    dates = ['신청기간: ' + period_text(facts, 'application'),
             '진행기간: ' + period_text(facts, 'operation'),
             '접수 상태: ' + reception_status(facts, now)]
    sessions = schedule_block(schedule_lines(view))
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
    content = normalize_schedule_heading(content, 'ko')
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
    # These same checks run before cleanup, so conflicting AI facts cannot be
    # hidden by removal/replacement of a generated row.
    validate_summary_period(content, canonical, view)
    content = normalize_summary_schedule(content, view)
    content = without_replaced_announcements(content, view)
    main = section_body(content, '[주요 내용]', KO_SECTION_HEADERS)
    fee_block = '\n'.join(line for line in sections['[주요 내용]'].splitlines()
                          if re.search(r'\*\*비용:', line))
    main = deduplicate_summary_fees(main, fee_block)
    boundary = '|'.join(re.escape(h) for h in KO_SECTION_HEADERS)
    content = re.sub(r'(?ms)(^\s*\[주요 내용\][ \t]*)(.*?)(?=^\s*(?:'+boundary+r')|\Z)',
                     lambda match: match[1]+'\n'+(main or '공식 안내의 프로그램 내용')+'\n', content, count=1)
    content = merge_reviewed_sections(content, sections)
    validate_participant_quantities(view, content)
    validate_assembled_fees(content, fee_block, canonical_block=fee_block)
    # Source tables are evidence. They are not blindly copied, but every
    # generated table is validated above before a candidate can be created.
    if schedule_tables(facts['description']) and not schedule_tables(content):
        raise AiJobError('ai_schema_error')
    return content
