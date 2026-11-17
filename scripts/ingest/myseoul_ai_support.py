"""MySeoul schedule and bilingual section validation."""
import re
import unicodedata

from ingest.ai_errors import ValidationError
from ingest.body_sections import KO_SECTION_HEADERS, JA_SECTION_HEADERS, normalize_schedule_heading


def schedule_values(text: str, *, japanese: bool = False) -> dict[str, set]:
    """Small typed check for explicit numeric dates, clock ranges and counts.

    No calendar expansion, AM/PM inference or general Japanese interpretation.
    """
    text = unicodedata.normalize("NFKC", text)
    weekdays = set(re.findall(r"([月火水木金土日])曜日?|[（(]\s*([月火水木金土日])\s*[）)]", text)) if japanese else set(
        re.findall(r"([월화수목금토일])\s*요일|[（(]\s*([월화수목금토일])\s*[）)]", text))
    alphabet = "月火水木金土日" if japanese else "월화수목금토일"
    days = {alphabet.index(a or b) for a, b in weekdays}
    if japanese:
        text = text.translate(str.maketrans({"年": "년", "月": "월", "日": "일", "時": "시", "分": "분", "回": "회"}))
    # A month explicitly governs only its contiguous list of numeric days.
    dates = set()
    for match in re.finditer(r"(\d{1,2})\s*월\s*((?:\d{1,2}\s*일?\s*[,·、・]\s*)*\d{1,2}\s*일)", text):
        dates.update((int(match[1]), int(day)) for day in re.findall(r"\d+", match[2]))
    years = {int(value) for value in re.findall(r"(\d{4})\s*년", text)}
    for year, month, day in re.findall(r'\b(\d{4})-(\d{2})-(\d{2})\b', text):
        dates.add((int(month), int(day)))
        years.add(int(year))
    clock = r"(?:\d{1,2}:[0-5]\d|\d{1,2}\s*시(?:\s*[0-5]?\d\s*분)?)"
    from ingest.translation_validation import midnight_closing
    def minutes(value: str, *, closing: bool = False) -> int:
        parts = [int(v) for v in re.findall(r"\d+", value)]
        if parts[0] > 23 and not (closing and parts in ([24], [24, 0])):
            raise ValidationError('clock', 'out_of_range', actual=parts)
        return parts[0] * 60 + (parts[1] if len(parts) > 1 else 0)
    times = {(minutes(m[1]), minutes(m[2], closing=midnight_closing(text[:m.start(2)]))) for m in re.finditer(
        rf"({clock})\s*(?:~|～|〜|–|—|-|부터|から)\s*({clock})", text)}
    counts = {int(v) for v in re.findall(r"(\d+)\s*회", text)}
    # Counted classes, not an exit number, attempt limit or an arbitrary '번'.
    if not japanese:
        counts.update(int(v) for v in re.findall(
            r"(\d+)\s*번\s*(?:의\s*)?(?:(?:실습\s*중심|실습|체험|이론|실기|온라인|오프라인)\s*)*(?:수업|교육|강의)", text))
    return {"dates": dates, "years": years, "weekdays": days, "times": times, "counts": counts}


def section_body(content: str, header: str, headers: tuple[str, ...]) -> str:
    """A real, nonempty section, not a label quoted inside another section."""
    if headers == KO_SECTION_HEADERS or headers == JA_SECTION_HEADERS:
        locale = 'ko' if headers == KO_SECTION_HEADERS else 'ja'
        content = normalize_schedule_heading(content, locale)
        header = normalize_schedule_heading(header, locale)
    boundary = "|".join(re.escape(h) for h in headers)
    matches = list(re.finditer(r"(?ms)^\s*" + re.escape(header) + r"[ \t]*(.*?)(?=^\s*(?:" + boundary + r")|\Z)", content))
    if len(matches) != 1 or not matches[0][1].strip():
        raise ValidationError('body_section', 'duplicate' if len(matches) > 1 else 'missing_or_empty',
                              expected=1, actual=len(matches))
    return matches[0][1].strip()
