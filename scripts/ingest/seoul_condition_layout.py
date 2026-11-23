"""Display-only roles for source-backed conditions, not new eligibility facts.

Keep unknown/compound conditions intact. Numbered procedures, cross-references,
date values and session ordinals are never stripped as generic list syntax.
"""
import re

from ingest.body_markdown import inline_text


def display_text(value):
    return re.sub(r'^[\s○❍●☞▹▶■□❐❏▪※►·*+\-]+', '', inline_text(value)).strip()


def compact(value):
    return re.sub(r'\s+', '', display_text(value)).rstrip('.。\\')


_CANCEL_HEADING = re.compile(r'^(?:예약\s*)?취소\s*(?:방법|절차)\s*[:：]\s*(.+)$')


def cancellation_steps(value):
    """Only a labelled procedure with a participant-facing channel or action."""
    match = _CANCEL_HEADING.fullmatch(display_text(value))
    if not match:
        return None
    steps = match[1]
    if (re.search(r'(?:마이\s*페이지|신청\s*(?:목록|내역)|예약\s*(?:번호|내역))'
                  r'.*?(?:[>→]|클릭|선택|취소(?:하세요|합니다|\s*신청))', steps)
            or re.search(r'(?:전화|이메일|홈페이지|온라인|방문)(?:로|으로|에서)?\s*(?:예약\s*)?'
                         r'(?:취소|신청|요청)|취소\s*(?:버튼|신청서를?\s*제출)', steps)):
        return steps
    return None


def cancellation_covers(longer, shorter):
    """Match a whole cancellation instruction, optionally followed by a qualification."""
    def comparable(line):
        text = re.sub(r'^(?:참가 조건|예약 절차|신청 안내|예약 취소)\s*[:：]\s*', '', display_text(line))
        detail = cancellation_steps(text) or text
        detail = re.sub(r'\s+(?:>|->|→)\s+', ' → ', detail).rstrip('.。\\').strip()
        return re.sub(r'번호(?:를)?\s*클릭(?:하여|해|해서)\s*취소(?:\s*진행|하세요|합니다)(?=[.,，。]|$)',
                      '번호 클릭하여 취소 진행', detail)

    full, part = comparable(longer), comparable(shorter)
    return full == part or ('취소' in part and full.startswith(part)
                            and re.match(r'^(?:[.。]\s+|[,，]\s*)(?:단,?|다만|기한|취소 기한|취소는|이용일|공연일|예외)',
                                         full[len(part):]) is not None)


def layout_role(value):
    text = display_text(value)
    if session_slot(text):
        return 'schedule'
    if booking_notice(re.split(r'\.\s+(?=단,|다만)', text, maxsplit=1)[0]):
        return 'booking'
    # Explicit contextual roles take precedence over words such as 전용/불가.
    if re.match(r'(?:주차(?:\s*안내)?|답사\s*코스(?:\s*\([^\n]+\))?)\s*[:：]', text):
        return 'activity'
    if re.match(r'답사지는\s*회차를', text):
        return 'activity'
    if re.match(r'(?:신청\s*기간|운영\s*일시)\s*[:：]', text):
        return 'schedule'
    if re.match(r'(?:\d+월\s*\d+일\([^()]+\)\s*[:：]|\d+회차\s*[–-]\s*\d{1,2}:\d{2})', text):
        return 'schedule'
    if re.match(r'(?:해당\s*회차\s*시작\(출발\)후에는|\d+회차\s*당\s*\d+분씩)', text):
        return 'schedule'
    if re.match(r'\d+회차\s*답사는', text):
        return 'schedule'
    if re.match(r'(?:모집\s*정원\s*[:：]|회차별\s*최대\s*\d+명\s*참여\s*가능)', text):
        return 'capacity'
    # Mixed participant eligibility is not reduced to a payment/booking rule.
    if re.search(r'보호자|동반|거주|국적|비자|학년|연령|\d+\s*세|가능자|소지자', text):
        return None
    if cancellation_steps(text):
        return 'booking'
    if (re.match(r'(?:참가\s*신청\s*[:：]|참\s*가비\s*[:：].*예약|\d+회\s*신청\s*시)', text)
            or re.match(r'(?:해당\s*)?프로그램은\s*선착순으로\s*모집', text)
            or re.match(r'프로그램\s*참여가\s*어려울\s*시,', text)
            or re.match(r'(?:참여\s*신청\s*후|예약\s*후\s*별도\s*연락|예약\s*신청\s*시\s*사진촬영)', text)
            or re.match(r'본\s*행사는.*사전\s*신청제로.*현장\s*접수', text)
            or re.match(r'행사\s*중\s*사진\s*촬영이.*신청\s*시', text)):
        return 'booking'
    return None


_EMPTY_HEADINGS = {'회차별운영시간', '신청및참여안내'}


def session_slot(value):
    # Only an entire numbered time range. Keep an attached qualifier intact.
    clock = r'([01]?\d|2[0-3])\s*(?::\s*([0-5]\d)|시(?:\s*([0-5]?\d)\s*분)?)'
    match = re.fullmatch(r'\((\d+)\s*회차\)\s*' + clock + r'\s*[-~～–]\s*' + clock, display_text(value))
    if match:
        number, h1, m1, k1, h2, m2, k2 = match.groups()
        return int(number), int(h1)*60 + int(m1 or k1 or 0), int(h2)*60 + int(m2 or k2 or 0)
    return None


def booking_notice(value):
    text = compact(value)
    rules = (
        ('per_guest', r'동반예약(?:의경우,?|도)(\d+)인당(\d+)예약(?:이)?필수입니다'),
        ('absent_without_cancel', r'사전취소없이불참(?:할경우,?|하면)이후프로그램신청이제한될수있습니다'),
        ('advance_cancel', r'(?:원활한진행을위해)?불참(?:시|할경우)최소(\d+)일전까지예약을취소해(?:주시기바랍니다|주세요)'),
    )
    for kind, pattern in rules:
        match = re.fullmatch(pattern, text)
        if match:
            return (kind, *match.groups())
    return None


def project_layout(value, lines):
    """Use only a uniquely matched current source line for contextual repairs."""
    text = display_text(value)
    matches = [i for i, line in enumerate(lines) if compact(line) == compact(value)]
    if len(matches) != 1:
        return [text]
    index = matches[0]
    text = re.sub(r'^✅\s*(?=대상\s*[:：])', '', text)
    notice = re.fullmatch(r'\d+[.)]\s*주의사항\s*[○●▪]\s*(.+)', text)
    if notice and not re.search(r'\d+\s*번\s*(?:항|조건)|\d+\s*항\s*참[고조]', '\n'.join(lines)):
        text = notice[1]
    if compact(re.sub(r'^⏰\s*', '', text)) in _EMPTY_HEADINGS:
        if any(line.strip() for line in lines[index + 1:]):
            return []
    numbered = re.fullmatch(r'\d+[.)]\s+(.+)', text)
    if (numbered and re.match(r'(?:해당\s*)?프로그램(?:은\s*선착순|\s*참여가\s*어려울\s*시,)', numbered[1])
            and layout_role(numbered[1]) == 'booking'
            and not re.search(r'\d+\s*번\s*(?:항|조건)|위\s*항|다음\s*단계|순서|먼저|그\s*다음', '\n'.join(lines))):
        text = numbered[1]
    audience = re.fullmatch(r'대상&인원\s*[:：]\s*([^/]+)\s*/\s*(회차당\s*최대\s*\d+명)', text)
    if audience:
        return ['대상: ' + audience[1].strip(), '정원: ' + audience[2]]
    previous = next((display_text(v) for v in reversed(lines[:index]) if v.strip()), '')
    if text.startswith('(') and re.fullmatch(r'주차\s*[:：]\s*장애인주차만\s*가능', previous):
        return ['주차 안내: ' + previous.split(':', 1)[-1].strip() + ' ' + text]
    # A route must have its own source heading. Carry that heading/date along
    # so another course is never silently attributed to the selected session.
    if re.match(r'^·\s*', value.strip()) and len(re.findall(r'\s[–-]\s', text)) >= 2:
        context = []
        for line in reversed(lines[max(0, index - 5):index]):
            if not line.strip():
                continue
            if re.match(r'^❏.*해설사\s*$', line.strip()):
                context.insert(0, display_text(line))
                return ['답사 코스 (' + ' / '.join(context) + '): ' + text]
            if re.fullmatch(r'\d+\.\d+\([^()]+\).*', display_text(line)):
                context.insert(0, display_text(line))
            else:
                break
    return [text]


def condition_signature(value):
    """Whole bounded clauses; numbers, deadlines, consequences and contact
    identity are part of equality. No keyword counts or fuzzy similarity.
    """
    text = compact(value)
    booking = booking_notice(value)
    if booking:
        return booking
    patterns = (
        ('accompanied_minor', r'어린이및청소년\(만(\d+)세이하\)은성인\(만(\d+)세이상\)이예약하고동반시참여가능합니다'),
        ('accompanied_minor', r'만(\d+)세이하는만(\d+)세이상성인이예약하고동반해야참여할수있습니다'),
        ('photo_consent', r'행사중사진촬영이이루어지며,신청시이에동의하는것으로간주합니다'),
        ('photo_consent', r'신청하면행사(?:중)?사진촬영에동의한것으로(?:간주합니다|봅니다)'),
        ('late_arrival_denied', r'해당회차시작\(출발\)후에는참여가불가능합니다'),
        ('late_arrival_denied', r'출발후에는참여할수없습니다'),
        ('no_show_restriction', r'예약후별도연락없이불참하실경우,추후신청이제한될수있습니다'),
        ('no_show_restriction', r'무연락불참은추후신청이제한될수있습니다'),
        ('photo_privacy', r'예약신청시사진촬영및개인정보활용에동의한것으로간주되며,사진외모든정보는당해년도사업홍보및결과보고서에사용후사업종료시폐기됩니다'),
        ('photo_privacy', r'예약시사진촬영·개인정보활용에동의한것으로간주합니다\.사진외정보는당해년도사업홍보·결과보고에사용후사업종료시폐기합니다'),
        ('payment', r'(?:해당)?프로그램은선착순으로모집되며,신청후(\d+)시간내에참여비를입금해야신청확정됩니다\.예약금(\d+(?:만|천)?원)을입금하지않을경우자동취소되고다음대기자분에게참여우선권이주어집니다'),
        ('payment', r'선착순모집이며,신청후(\d+)시간이내에예약금(\d+(?:만|천)?원)을입금해야신청이확정됩니다\.미입금시자동취소되며다음대기자에게참여우선권이주어집니다'),
        ('refund', r'프로그램참여가어려울시,이용일로부터(\d+)시간전까지환불수수료없이전액환불가능하며그이후에는환불불가하므로참고바랍니다\.\(\*?참여불가시(.+?)으로별도문의필수\)'),
        ('refund_reverse', r'참여가어려우면(.+?)으로반드시별도문의해주세요\.이용일로부터(\d+)시간전까지는환불수수료없이전액환불되며,이후에는환불되지않습니다'),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            if kind == 'refund_reverse':
                return ('refund', match[2], match[1])
            return (kind, *match.groups())
    return None


def parking_signature(value):
    text = compact(value)
    condition = r'장애인전용주차구역주차\(가능\)표지부착차량에보행상장애가있는사람이탑승한경우'
    if (re.fullmatch(r'주차안내:장애인주차만가능\(' + condition + r'\)', text)
            or re.fullmatch(r'공원내주차는' + condition + r'에만가능합니다', text)):
        return ('accessible_parking_only_with_passenger',)
    return None
