"""Source text printed in a reservation's detail images. No image fetch or OCR."""
import re

# Require an activity statement, not a genre/name or a reservation notice alone.
_ACTIVITY = re.compile(
    r'(?:공연|콘서트|연주회|전시).{0,24}(?:관람가|감상합니다|관람합니다|선보입니다|연주합니다|진행합니다|개최합니다)'
    r'|(?:곡|음악|작품|악기)(?:을|를).{0,24}(?:연주|감상|관람)(?:합니다|할 수 있)'
    r'|(?:체험|수업|강좌|교육|해설|탐방|실습|워크숍).{0,40}(?:배웁니다|체험합니다|진행합니다|만듭니다|실습합니다)')
_ALL_AGES = re.compile(r'전체\s*관람가|모든\s*연령(?:층)?\s*(?:관람|참여)\s*가능')
_TICKETS = re.compile(r'(?:관람객|관람\s*인원|관람자|관객)\s*(?:수\s*)?(?:만큼|당|마다)\s*(?:각각\s*)?(?:신청|예매|예약)(?:해\s*주|해야|하셔야|하세요|합니다|이\s*필요)')
_INDIVIDUAL = re.compile(r'(?:개인|누구나)\s*(?:예매|신청|예약|참여)(?:은|는|이|가)?\s*(?:가능합니다|할 수 있습니다|가능(?=\s*(?:[.!。,]|\n|$)))')
_GROUP = re.compile(r'(?:기관|학교|단체)\s*(?:신청|예약|접수|참여)?\s*(?:만\s*(?:가능|신청|예약|접수|참여)|전용|한정)|개인\s*(?:예약|신청|접수)(?:은|는|이|가)?\s*불가')
_CASTING = re.compile(r'(?:출연(?:자|진|팀)|공연팀|연주자|공연자|예술인)\s*(?:공개\s*)?(?:모집|선발|공모)|(?:모집|선발)\s*대상\s*[:：]\s*(?:출연자|예술인)')
_CONDITION = re.compile(r'대상|관람|예약|신청|환불|보증금|취소|불가|필수|예외|입장|문의|수수료|주의|제한|원\b|세\s*이상|전용|촬영|준비물|이용|동반|정원|선착순|마감|입실|신분증|매표|유료|무료')
_AGE = re.compile(r'(?:만\s*)?(\d{1,2})\s*세\s*이상|성인\s*(?:만|전용)|미성년자\s*(?:관람|입장)\s*불가')
_FILE = re.compile(r'(?:https?://\S+|[^\n]+\.(?:jpe?g|png|gif|webp|svg|pdf))', re.I)


def _quote_key(value):
    return re.sub(r'\s+', ' ', value).strip()


def placeholder_description(text, title):
    compact = _quote_key(text)
    if compact == _quote_key(title):
        return True
    return bool(re.fullmatch(
        r'(?:(?:자세한|상세한?)\s*)?(?:프로그램\s*|행사\s*)?(?:설명|안내|내용)(?:은|는|을|를)?\s*'
        r'(?:(?:아래|위|첨부)(?:의|된)?\s*)?(?:이미지|포스터|첨부파일)(?:에서|를|을|로)?\s*'
        r'(?:확인|참고)(?:해\s*주세요|하세요|하시기\s*바랍니다)[.!]?', compact))


def _age_limits(text):
    limits = {m.group(1) or '성인' for m in _AGE.finditer(text)}
    for match in re.finditer(r'(청소년|어린이|초등학생|성인)\s*(?:전용|만\s*(?:관람|입장|참여|신청))', text):
        limits.add(match.group(1))
    return limits


def detail_image_evidence(details, title, target, alts):
    quotes = {}
    for alt in alts:
        quote = alt.strip()
        key = _quote_key(quote)
        if key and key != _quote_key(title) and not _FILE.fullmatch(key):
            quotes.setdefault(key, quote)
    performance_title = re.search(r'공연|콘서트|연주회|전시', title)
    activity = [q for k, q in quotes.items()
                if (_ACTIVITY.search(k) or (performance_title and _ALL_AGES.search(k) and _TICKETS.search(k)))
                and not re.search(r'(?:진행|개최|실시)\s*(?:여부|하지\s*않)'
                                  r'|(?:관람가|관람)\s*(?:가\s*)?(?:아님|아닙|불가|미정)', k)]
    relevant = [q for q in quotes.values()
                if q in activity or _CONDITION.search(q) or _GROUP.search(q) or _CASTING.search(q) or _age_limits(q)]
    if not relevant:
        return None
    alt_text = '\n'.join(relevant)
    ordinary = '\n'.join([details, target])
    combined = '\n'.join([ordinary, alt_text])
    conflicts = []
    ordinary_limits, alt_limits = _age_limits(ordinary), _age_limits(alt_text)
    if ((_ALL_AGES.search(alt_text) and (ordinary_limits or alt_limits))
            or (_ALL_AGES.search(ordinary) and alt_limits)
            or (ordinary_limits and alt_limits and ordinary_limits != alt_limits)):
        conflicts.append('target_conflict')
    group = bool(_GROUP.search(combined))
    ticket_booking = bool(_ALL_AGES.search(combined) and _TICKETS.search(combined))
    booking_uncertain = re.search(
        r'(?:관람|예약|신청|예매)\s*(?:가능\s*)?(?:여부|미정|불명확)'
        r'|(?:예약|예매)(?:(?:이|은)?\s*|해\s*(?:주실|야\s*할)\s*)필요\s*(?:가\s*)?(?:없|하지\s*않)'
        r'|전체\s*관람가(?:가)?\s*(?:아님|아닙|미정)', combined)
    personal = not booking_uncertain and bool(_INDIVIDUAL.search(combined) or ticket_booking)
    if group and personal:
        conflicts.append('application_actor_conflict')
    fallback = bool(activity) and len(details.strip()) < 20
    recruitment = bool(_CASTING.search(title + '\n' + combined))
    additional_restriction = (bool(_GROUP.search(alt_text)) and not _GROUP.search(ordinary)
                              or bool(_CASTING.search(alt_text)) and not _CASTING.search(title + '\n' + ordinary))
    if not fallback and not conflicts and not additional_restriction:
        return None
    return {'source': 'DTLCONT.img.alt', 'quotes': relevant, 'used_for_description': fallback,
            'audience_booking': personal, 'group_only': group,
            'recruitment': recruitment, 'conflicts': conflicts}
