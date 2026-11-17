"""Verified Seoul Reservation venues. Only an activity or meeting role supplies evidence."""
import re
from dataclasses import dataclass

from ingest.seoul_evidence import VENUE_LABELS, _clean, _venue_lines, label_match, variable_venue


@dataclass(frozen=True)
class Venue:
    address: str
    source: str
    gate: str = ""

    @property
    def district(self):
        return self.address.split()[1]


# Facility addresses checked against the operators' visitor guides on 2026-11-17.
PALACES = "https://royal.khs.go.kr/ROYAL/contents/R707000000.do"
VENUES = {
    "경복궁": Venue("서울특별시 종로구 사직로 161", PALACES, "광화문"),
    "창덕궁": Venue("서울특별시 종로구 율곡로 99", PALACES + "?schGroupCode=cdg&schGroupCodeNm=%EC%B0%BD%EB%8D%95%EA%B6%81", "돈화문"),
    "창경궁": Venue("서울특별시 종로구 창경궁로 185", PALACES + "?schGroupCode=cgg", "홍화문"),
    "덕수궁": Venue("서울특별시 중구 세종대로 99", PALACES + "?schGroupCode=dsg", "대한문"),
    "서울공예박물관": Venue("서울특별시 종로구 율곡로3길 4", "https://craftmuseum.seoul.go.kr/preview/visit"),
    "선유도공원": Venue("서울특별시 영등포구 선유로 343", "https://parks.seoul.go.kr/maps/seonyudo/seonyudo_map_KR.pdf"),
    "월드컵공원": Venue("서울특별시 마포구 월드컵로 243-60", "https://parks.seoul.go.kr/park/detailView.do?pIdx=6"),
}

MEETING = ("집결지", "집결장소", "집합장소", "출발지", "출발장소", "만나는곳", "모이는곳", "모이는장소")
SESSION = re.compile(r"(?<!\d)(\d+)\s*(회차|코스)")
ACTUAL = re.compile(r"(.+?)에서\s*(?:집결(?:합니다)?|출발(?:합니다)?|(?:전시\s*해설|교육|체험)(?:을|를)\s*(?:진행|운영)합니다)[.!]?$")
ARRIVAL = re.compile(r"\s*(?:[(（*※]\s*)(?:출발|시작)\s*\d+\s*분\s*전까지\s*도착(?:\s*(?:요망|필수|해\s*주세요))?\s*[)）.!]?\s*$")
CONDITIONAL_VENUE = re.compile(
    r"(?:우천|악천후|예비|경우|대체|변경\s*시|[월화수목금토일]요일|[A-Z]\s*코스).*"
    r"(?:집결|집합|출발|장소|개최지|에서\s*진행|으로\s*변경)")
DIRECTIONS = re.compile(r"^(?:찾아\s*오시는\s*길|찾아\s*오는\s*길|교통\s*안내|대중교통(?:\s*이용)?(?:\s*안내)?)"
                        r"(?:[\]】\s:：]|$)")


def _onsite_point(value, name):
    venue = VENUES[name]
    points = ["정문", "입구", "매표소", "안내데스크", "교육실", "전시실"]
    if venue.gate:
        points.append(venue.gate)
    suffix = "|".join(points)
    address = re.escape(venue.address)
    locality = rf"(?:(?:서울특별시|서울시|서울)\s+)?{venue.district}"
    match = re.fullmatch(
        rf"(?:(?:{address}|{locality})\s+)?({name}(?:\s+(?:{suffix}))*"
        rf"(?:\s*앞)?)(?:\s*\({address}\))?(?:\s+(?:집결|출발))?[.!]?", ARRIVAL.sub("", value))
    return match[1] if match else None


@dataclass(frozen=True)
class VenueEvidence:
    name: str
    quote: str
    point: str

    def filter_value(self):
        venue = VENUES[self.name]
        return {"scope": "specific", "venues": [
            {"province": "11", "district": venue.district, "facility": self.point, "address": venue.address}
        ]}


# None delegates unrelated locations to the existing source reader.
# An empty tuple means a catalog reference was considered but could not be grounded.
def reservation_venue_evidence(text, raw, locations, title="") -> tuple[VenueEvidence, ...] | None:
    if not any(name in text or any(name in value for value in locations) for name in VENUES):
        return None
    active = set(SESSION.findall(title))
    if re.search(r"\d\s*[-~～,/·및과와]\s*\d+\s*(?:회차|코스)", title):
        active.clear()
    sessions = set(SESSION.findall(text))
    scoped = len(sessions | active) > 1 or bool(sessions - active)
    candidates = []
    position_notes = []
    mentioned = False
    unresolved = False
    other_context = False
    varies = variable_venue(text + "\n" + str(raw.get("PLACENM", "")))
    lines = text.splitlines()
    headings = ["오시는 길" if DIRECTIONS.match(_clean(line).lstrip("[【 ")) else line for line in lines]
    eligible_lines = _venue_lines("\n".join(headings), exclude_directions=True)
    for i, (original, eligible) in enumerate(zip(lines, eligible_lines)):
        line = _clean(original)
        if re.match(r"^[\[【(]?(?:예시|지난\s*회차|이전\s*회차|다른\s*(?:회차|코스)|변경\s*전)(?:[\]】)\s:：]|$)", line):
            other_context = True
        if re.fullmatch(r"(?:[A-Z가-힣]+\s*코스|[월화수목금토일]요일|오전반|오후반|\d+월\s*\d+일)",
                        line.strip("[]【】:： ")):
            other_context = True
        if re.match(r"^(?:이번|해당)\s*회차\s+", line):
            other_context = False
            line = re.sub(r"^(?:이번|해당)\s*회차\s+", "", line)
        tag = re.match(r"^\[?(?:제\s*)?(\d+)\s*(회차|코스)\]?\s*[:：-]?\s*", line)
        if tag:
            line = line[tag.end():]
        role = label_match(line, MEETING + VENUE_LABELS)
        natural = ACTUAL.fullmatch(line)
        if not (role or natural):
            if eligible and CONDITIONAL_VENUE.search(line):
                unresolved = True
            continue
        value = role[1] if role else natural[1]
        quote = original.strip()
        end = i
        if role and not value and i + 1 < len(lines) and eligible_lines[i + 1]:
            end += 1
            value = lines[end].strip()
            quote = (original + "\n" + lines[end]).strip()
        names = [name for name in VENUES if name in value]
        mentioned |= bool(names)
        if not eligible or other_context or (tag and len(active) == 1 and tag.groups() not in active):
            continue
        following = lines[end + 1].strip() if end + 1 < len(lines) else ""
        if re.match(r"^(?:또는|혹은|→|대신|미정|추후\s*안내|변경\s*(?:예정|가능)|역\s*\d+\s*번\s*출구)", following):
            unresolved = True
            continue
        if len(names) != 1 or ((scoped or varies) and not (tag and active == {tag.groups()})):
            unresolved = True
            continue
        name = names[0]
        venue = VENUES[name]
        # Only a known onsite qualifier may follow the whole venue name. In
        # particular an adjacent station, branch, café or route is not an alias.
        point = _onsite_point(value, name)
        if not point or (raw.get("AREANM") and raw["AREANM"] != venue.district):
            unresolved = True
            continue
        entry = VenueEvidence(name, quote, point)
        if role and role[0] == "위치":
            position_notes.append(entry)
        else:
            candidates.append(entry)

    if not mentioned and not any(name in v for name in VENUES for v in locations):
        return None
    if unresolved or not candidates:
        return ()
    if re.search(r"(?:집결(?:지|장소)|출발지|개최지|장소)\s*(?:는|가|를)?\s*"
                 r"(?:미정|추후\s*(?:안내|공지)|변경\s*(?:될|예정))", text):
        return ()
    cited = candidates + position_notes
    if len({c.name for c in cited}) != 1:
        return ()
    name = candidates[0].name
    registered = raw.get("PLACENM") or ""
    if registered and not _onsite_point(registered, name):
        return ()
    # A separate table cell or unmatched venue line cannot silently disappear.
    ignored_lines = [line for line, eligible in zip(lines, eligible_lines) if not eligible]
    if any(not any(v in c.quote for c in cited) and not any(v in line for line in ignored_lines)
           for v in locations):
        return ()
    # A more precise onsite point may qualify a general venue. Two different
    # meeting points need a human to choose, even within the same district.
    points = {c.point for c in candidates} - {name}
    if len(points) > 1:
        return ()
    return (next(c for c in candidates if not points or c.point in points),)
