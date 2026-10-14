"""Seoul public presentation only; never changes stored status or temporal gates."""
from __future__ import annotations
import re
from urllib.parse import urlsplit, parse_qs
from ingest.ai_errors import AiJobError
from ingest.body_markdown import inline_text
from ingest.seoul_fact_roles import optional_section

# Only a dedicated state field or a complete 'currently ...' sentence is a
# snapshot display. Dates, conditional reception and causal closure notices
# are not matched by these anchored forms.
_STATES = {
    'ko': r'(?:접수\s*중|예약\s*마감|접수\s*(?:마감|종료)|신청\s*시작\s*전|운영\s*종료)',
    'ja': r'(?:受付中|予約受付終了|予約締切|受付終了|受付締切|申請開始前|運営終了)',
}
_LABELS = {
    'ko': r'(?:접수\s*상태|현재\s*접수\s*상태|신청\s*마감)',
    'ja': r'(?:受付状況|現在の受付状況|申請締切)',
}
_CURRENT = {
    'ko': r'(?:현재|지금)(?:은|는)?\s*(?:(?:접수|예약|신청|운영)\s*(?:상태는|은|는|이|가)\s*)?',
    'ja': r'現在(?:は|、|の受付状況は)?\s*',
}
_END = {'ko':r'(?:입니다|상태입니다|되었습니다|됐습니다)?', 'ja':r'(?:です|となっています|しています)?'}

def _status_only(text: str, locale: str) -> bool:
    text = re.sub(r'^\s*[-+*]\s+', '', inline_text(text)).strip()
    return bool(re.fullmatch(rf'(?:{_LABELS[locale]}\s*[:：]\s*)?{_STATES[locale]}{_END[locale]}[.。]?|'
        rf'{_CURRENT[locale]}{_STATES[locale]}{_END[locale]}[.。]?', text))

def without_reception_status(content: str, locale: str = 'ko') -> str:
    result = []
    for line in content.splitlines():
        if _status_only(line, locale):
            continue
        # A labelled state followed by a unique condition retains that condition.
        label = re.match(rf'^\s*(?:[-+*]\s+)?(?:\*\*)?{_LABELS[locale]}\s*[:：](?:\*\*)?\s*'
                         rf'{_STATES[locale]}(?:\*\*)?\s*[,;；/]\s*(.+)$', line)
        if label:
            result.append(label[1])
            continue
        # Remove only complete standalone current-state sentences. Normal date
        # separators, tables/lists and the other sentences stay unchanged.
        pieces = re.split(r'(?<=[.。])(?=\s|$)', line)
        kept = []
        for piece in pieces:
            if _status_only(piece, locale):
                continue
            connector = r'(?:이며|이고|이지만|지만)[,]?\s*' if locale == 'ko' else r'ですが[、,]?\s*'
            clause = re.match(rf'^\s*{_CURRENT[locale]}{_STATES[locale]}{connector}(.+)$', piece)
            kept.append(clause[1] if clause else piece)
        result.append(''.join(kept).lstrip() if kept != pieces else line)
    return '\n'.join(result).strip()

def official_reservation_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        u = urlsplit(value)
        query = parse_qs(u.query, keep_blank_values=True)
        if (u.scheme != 'https' or u.netloc != 'yeyak.seoul.go.kr' or u.fragment
                or u.path != '/web/reservation/selectReservView.do'
                or set(query) != {'rsv_svc_id'} or len(query['rsv_svc_id']) != 1
                or not re.fullmatch(r'[A-Za-z0-9_-]+', query['rsv_svc_id'][0])):
            return None
        return value if re.fullmatch(r'https://yeyak\.seoul\.go\.kr/web/reservation/selectReservView\.do\?rsv_svc_id=[A-Za-z0-9_-]+', value) else None
    except ValueError:
        return None

_ROUTE = re.compile(r'전화\s*(?:신청|예약|접수)|(?:인터넷|온라인)\s*(?:신청|예약|접수)|'
                    r'(?:현장|방문)\s*(?:신청|예약|접수)|(?:전화|방문)[^\n.。]{0,140}(?:협의|조율)|'
                    r'예약\s*(?:방법|절차)\s*[:：]|검색\s*(?:→|->)[^\n]{1,140}(?:신청|예약)')

def _has_route(method: str) -> bool:
    text = inline_text(method)
    for match in _ROUTE.finditer(text):
        tail = re.split(r'[.!?。\n]', text[match.end():], maxsplit=1)[0]
        if not re.search(r'불가|금지|명시되지|안내되지|(?:안내|명시)되어\s*있지\s*않|미표기|없|하지\s*않', tail):
            return True
    return False

def ensure_application_guidance(content: str, facts: dict) -> str:
    from ingest.myseoul_content import merge_reviewed_sections
    method = optional_section(content, '[신청 방법]')
    url = official_reservation_url(facts.get('official_url'))
    if url and re.search(re.escape(url) + r'(?=$|[\s)])', method):
        return content
    # Existing validated method rows/procedures take precedence. A contact
    # number alone, cancellation notice or 'not specified' is not a route.
    if method.strip() and (facts.get('application_methods') or _has_route(method)):
        return content
    fallback = (f'구체적인 신청 방법은 공식 안내에서 확인해 주세요.\n\n[공식 예약 페이지]({url})'
                if url else '구체적인 신청 방법은 확인되지 않았습니다. 제공 기관에 확인해 주세요.')
    if fallback in method:
        return content
    return merge_reviewed_sections(content, {'[신청 방법]': fallback})

def validate_public_guidance(content: str, locale: str) -> None:
    if without_reception_status(content, locale) != content.strip():
        raise AiJobError('ai_schema_error')
    # Unknown/mixed status fields are not silently accepted or erased. They
    # need a new verified result; conditions must never be discarded to pass.
    label = r'(?:현재\s*)?접수\s*상태' if locale == 'ko' else r'(?:現在の)?受付状況'
    if re.search(r'(?m)^\s*(?:[-+*]\s+)?' + label + r'\s*[:：]', inline_text(content)):
        raise AiJobError('ai_schema_error')
    header = '[신청 방법]' if locale == 'ko' else '[申請方法]'
    from ingest.ai_worker import KO_SECTION_HEADERS, JA_SECTION_HEADERS
    from ingest.myseoul_ai_support import section_body
    if not section_body(content, header, KO_SECTION_HEADERS if locale == 'ko' else JA_SECTION_HEADERS).strip():
        raise AiJobError('ai_schema_error')
