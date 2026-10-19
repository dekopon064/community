"""Pure venue/quote linkage. No auth, network, persistence or item exceptions."""
from __future__ import annotations
import re
import unicodedata
from urllib.parse import urldefrag


def location_key(value):
    # Delimiters are display differences; digits/directions/branch names remain.
    value=unicodedata.normalize('NFKC', value).replace('內', '내')
    value=re.sub(r'((?:공원|전시관|박물관|센터))\s+(?:내|안)\s+', r'\1 ', value)
    return re.sub(r'[\s·ㆍ,()[\]「」『』×\-]', '', value)


MEETING = r'(?:만나는\s*(?:장소|곳)|만남(?:의)?\s*장소|모이는\s*(?:장소|곳)|모임\s*장소|집결\s*(?:장소|지)|출발\s*장소)'
VENUE = r'(?:개최\s*장소|운영\s*장소|활동\s*장소|장\s*소)'
FACILITY = r'[가-힣A-Za-z0-9 ]+?(?:가드닝센터|지원센터|여가센터|힐링센터|문화센터|체험센터|전시관|체험관|과학관|박물관|도서관|플레이스|공원|창포원|광장|성당|전시실|센터|체험원|마을|궁|역)'


def meeting_places(description):
    return [m.group(1).strip() for m in re.finditer(
        r'(?:^|\n)[^\w가-힣\n]*(?:\d+[).]\s*)?'+MEETING+r'\s*(?:\*{1,2}|__)?\s*[:：]\s*(?:\*{1,2}|__)?([^\n]+)', description)]


def facility_name(place):
    m = re.match(FACILITY, place.strip())
    return m.group(0).strip() if m else re.sub(r'\s+(?:앞|뒤)$','',place.strip())


def _qualifiers(value):
    return set(re.findall(r'(?:\d+(?:번)?출구|[Bb]?\d+층|\d+(?:교육실|호실|실)|정문|후문|동문|서문|남문|북문)', location_key(value)))


def venue_matches(place, anchor):
    p, a = location_key(place), location_key(anchor)
    if p in a:
        return True
    base = facility_name(place)
    if len(location_key(base)) < 3 or location_key(base) not in a:
        return False
    # An added or conflicting exit/room/direction cannot borrow a building address.
    if not _qualifiers(place).issubset(_qualifiers(anchor)):
        return False
    # Only extra parenthetical aliases may follow a fully anchored base. Do not
    # silently accept arbitrary new rooms, branches or landmarks after the base.
    tail = place[len(base):].strip()
    return not tail or bool(re.fullmatch(r'\([^()]+\)', tail)) and location_key(tail) in a


def source_link(title, description, place):
    meetings = meeting_places(description)
    if re.search(MEETING, description) and not meetings:
        return False, 'meeting_not_explicit'
    if meetings:
        if len(set(map(location_key, meetings))) != 1:
            return False, 'meeting_multiple'
        return venue_matches(place, meetings[0]), 'meeting'
    location_lines = [m.group(1) for m in re.finditer(
        r'(?:^|\n)[^\w가-힣\n]*(?:\d+[).]\s*)?'+VENUE+r'\s*[:：]\s*([^\n]+)', description)]
    if location_lines:
        return any(venue_matches(place, line) for line in location_lines), 'venue'
    # A title can supply a venue only if there is no explicit, different meeting
    # or venue. Never use an organizer/contact/parking line as a venue.
    if venue_matches(place, title):
        return True, 'title'
    lines = [line for line in description.splitlines() if venue_matches(place, line)]
    if not lines:
        return False, 'place_not_in_source'
    bad = r'(?:기관\s*주소|문의처|주차장\s*(?:주소|위치)|오시는\s*길|수령\s*장소|운영\s*구간|이동\s*경로)\s*[:：]'
    return not all(re.search(bad, line) for line in lines), 'description'


def quote_link(place, excerpt, province, district):
    base = facility_name(place)
    if base in {'교육실','전시실','회의실','세미나실','체험실','센터','공원','광장','도서관','박물관','과학관','입구'}:
        return False
    regions={(m.group(1)[:2],m.group(2)) for m in re.finditer(
        r'(서울(?:특별시|시)?|경기(?:도)?|인천(?:광역시)?)\s+([가-힣]+(?:구|시|군))',excerpt)}
    if regions and regions!={(province,district)}:
        return False
    def exits(value):
        return {n for m in re.finditer(r'(\d+(?:\s*[,·/]\s*\d+)*)\s*번?\s*출구', value)
                for n in re.findall(r'\d+',m.group(1))}
    requested, cited=exits(place),exits(excerpt)
    if requested and cited and not requested.issubset(cited):
        return False
    return (len(location_key(base)) >= 3 and location_key(base) in location_key(excerpt)
            and province in excerpt and district in excerpt)


def source_region_conflict(description, place, province, district):
    meetings=meeting_places(description)
    lines=meetings or [line for line in description.splitlines()
        if location_key(facility_name(place)) in location_key(line)
        and not re.search(r'기관\s*주소|문의처|주차장|수령\s*장소',line)]
    for line in lines:
        for m in re.finditer(r'(서울(?:특별시|시)?|경기(?:도)?|인천(?:광역시)?)\s+([가-힣]+(?:구|시|군))',line):
            if not m.group(1).startswith(province) or m.group(2)!=district:
                return True
    return False


def url_identity(value):
    """Preserve reserved separators, query order/duplicates and encoded slashes."""
    raw = urldefrag(value)[0]
    def decode(m):
        char = chr(int(m.group(1), 16))
        return char if re.fullmatch(r'[A-Za-z0-9_~()\-]', char) else '%'+m.group(1).upper()
    return re.sub(r'%([0-9A-Fa-f]{2})', decode, raw)


def verified_quote(excerpt, page):
    """Separate prose from *literal cited spans*, never manufacture a quotation.

    Every explicitly quoted span must exist. Legacy slash/pipe-separated exact
    fields are supported, but an invented address is never discarded to pass.
    """
    normalized, positions = [], []
    for i, char in enumerate(page):
        for c in unicodedata.normalize('NFKC', char):
            if not c.isspace():
                normalized.append(c); positions.append(i)
    text = ''.join(normalized)
    def locate(part):
        key = re.sub(r'\s+', '', unicodedata.normalize('NFKC', part))
        at = text.find(key)
        return page[positions[at]:positions[at+len(key)-1]+1] if key and at >= 0 else None
    whole = locate(excerpt)
    if whole:
        return whole, '', [whole]
    quoted = re.findall(r'[“「『"]([^”」』"\n]+)[”」』"]', excerpt)
    parts = quoted or [p.strip() for p in re.split(r'\s+(?:/|\||—)\s+|\n+', excerpt) if p.strip()]
    def unlabel(p):
        return re.sub(r'^(?:◎\s*)?(?:집결\s*장소|출발\s*장소|장소|주소)\s*[:：|]\s*', '', p)
    found = [locate(p) or locate(unlabel(p)) for p in parts]
    if not parts or not all(found):
        return None, '', []
    # Unquoted prose may explain the citations, but must not introduce another
    # location/address claim. Such claims need their own verbatim support.
    explanation = excerpt
    for p in quoted:
        explanation = explanation.replace(p, '')
    if quoted and re.search(r'(?:서울|경기|인천)[가-힣]*\s+[가-힣]+(?:구|시|군)|\d+번\s*출구|\d+층', explanation):
        return None, '', []
    unique = list(dict.fromkeys(found))
    return '\n'.join(unique), explanation if quoted else '', unique


def facility_quote(place, page):
    """A bounded, exact facility-name span; never a guessed address."""
    base=facility_name(place)
    pattern=r'\s*'.join(re.escape(c) for c in base if not c.isspace())
    match=re.search(pattern,page) if len(location_key(base))>=3 else None
    return match.group(0) if match else None


def page_location_link(item, place, quote, page, province, district):
    """Avoid combining one facility's name with another address or site footer."""
    base = facility_name(place)
    if not quote_link(place, quote, province, district):
        return False
    # Restrict location evidence to visible content before shared site footer.
    body=page
    footers=list(re.finditer(r'이메일\s*무단수집거부|서울특별시청\s*04524',page))
    if footers:
        body=page[:footers[0].start()]
    if location_key(base) not in location_key(body):
        return False
    title = location_key(item['title'])
    venue_labels=re.findall(r'(?:Location|장소명\s*[:：])\s*([^\n]{1,200})',body)
    if len(title)>=5 and title in location_key(body) and venue_labels and not any(
            location_key(base) in location_key(label) for label in venue_labels):
        return False
    # A local passage explicitly joins the facility and its province/district.
    flat = re.sub(r'\s+', ' ', body)
    for m in re.finditer(re.escape(district), flat):
        context = flat[max(0,m.start()-140):m.end()+140]
        if province not in context or location_key(base) not in location_key(context):
            continue
        # Another facility heading before the address is not a link to ours.
        after_base=context[context.find(base)+len(base):] if base in context else ''
        if re.search(r'\s+[가-힣A-Za-z0-9]{2,}(?:공원|센터|도서관|과학관|박물관|전시관)\s', after_base):
            continue
        if len(set(re.findall(r'(?:서울(?:특별시|시)?|경기(?:도)?|인천(?:광역시)?)\s+([가-힣]+(?:구|시|군))',context)))>1:
            continue
        return True
    # The current reservation page may put its venue header and map far apart.
    # Only that same programme's title + a labelled map-address field can link.
    if venue_labels and not any(location_key(base) in location_key(label) for label in venue_labels):
        return False
    maps=re.findall(r'지도\s*주소\s*(서울(?:특별시|시)?|경기(?:도)?|인천(?:광역시)?)\s+([가-힣]+(?:구|시|군))',body)
    return (len(title) >= 5 and title in location_key(body) and bool(maps)
            and all(p.startswith(province) and d==district for p,d in maps))
