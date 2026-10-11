"""Small explicit translation checks, not a Japanese semantic interpreter.

Only the supplied Korean text is authoritative. Never repair provider output,
fetch evidence or infer unstated values. Contextual wording remains a review task.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import unicodedata

from ingest.ai_errors import AiJobError
from ingest.body_sections import normalize_schedule_heading

_HEADERS = {
    "한 줄 요약": "要約", "대상": "対象", "일정 안내": "日程案内",
    "주요 내용": "主な内容", "신청 방법": "申請方法",
}
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_URL = re.compile(r"https?://[^\s<>\"'）)\]。、「」]+")
# Only explicit labeled entries are checked by role. Synonymous Japanese labels
# are accepted; unlabeled prose is not interpreted as a new eligibility policy.
_PERIOD_ROLES = (
    (r"신청\s*기간", r"(?:申請|申込|申し込み|応募|募集|受付)(?:受付)?期間"),
    (r"진행\s*기간|개최\s*기간", r"(?:実施|開催|実施・開催)期間"),
    (r"집결\s*(?:안내|시간)", r"集合(?:案内|時間|時刻)?"),
    (r"신청\s*마감", r"(?:申請|申込|申し込み|応募|受付)(?:締切(?:日)?|期限)|締切(?:日)?"),
)
_FEE_ROLES = (
    (r"수강료", r"受講料|授業料"), (r"입장료", r"入場料"),
    (r"재료비", r"材料費"), (r"기타\s*비용", r"その他(?:の)?(?:費用|料金)|追加料金"),
)


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _amounts(text: str, *, japanese: bool) -> Counter:
    pattern = rf"({_NUMBER})\s*(?:(만|천)\s*)?원" if not japanese else rf"({_NUMBER})\s*ウォン"
    values = Counter()
    for match in re.finditer(pattern, text):
        # Decimal arithmetic retains fractional 만/천 values exactly.
        amount = Decimal(match[1].replace(",", ""))
        if not japanese:
            amount *= {None: 1, "만": 10000, "천": 1000}[match[2]]
        values[amount] += 1
    return values


def _quantities(text: str, *, japanese: bool) -> Counter:
    units = r"名|人|歳|回" if japanese else r"명|세|회"
    unit_names = {"名": "people", "人": "people", "명": "people",
                  "歳": "age", "세": "age", "回": "count", "회": "count"}
    comparisons = {None: None, "이상": "minimum", "以上": "minimum",
                   "이하": "maximum", "以下": "maximum", "미만": "under", "未満": "under",
                   "초과": "over", "超": "over"}
    suffix = r"以上|以下|未満|超" if japanese else r"이상|이하|미만|초과"
    quantities = Counter()
    spans = []
    # A shared unit in an inclusive range is not an omitted first endpoint.
    for match in re.finditer(rf"(\d[\d,]*)\s*({units})?\s*[~～〜-]\s*(\d[\d,]*)\s*({units})", text):
        if match[2] is not None and unit_names[match[2]] != unit_names[match[4]]:
            continue
        quantities[(int(match[1].replace(',', '')), unit_names[match[4]], 'minimum')] += 1
        quantities[(int(match[3].replace(',', '')), unit_names[match[4]], 'maximum')] += 1
        spans.append(match.span())
    for match in re.finditer(rf"(\d[\d,]*)\s*({units})\s*({suffix})?", text):
        if not any(start <= match.start() < end for start, end in spans):
            quantities[(int(match[1].replace(',', '')), unit_names[match[2]], comparisons[match[3]])] += 1
    return quantities


def _first_come(text: str, *, japanese: bool) -> Counter:
    pattern = (r"先着(?:順)?[で、\s]*(\d[\d,]*)\s*(?:名|人)|"
               r"(\d[\d,]*)\s*(?:名|人)[（(、\s]*先着(?:順)?") if japanese else r"선착순\s*(\d[\d,]*)\s*명"
    return Counter(int(next(v for v in match.groups() if v).replace(",", ""))
                   for match in re.finditer(pattern, text))


def _durations(text: str) -> Counter:
    # Duration, not a clock (3시간 / 3時間), with equivalent hour/minute units.
    result = Counter()
    for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:시간|時間)(?:\s*(\d+)\s*(?:분|分))?|'
                             r'(\d+)\s*(?:분간|分間)', text):
        minutes = Decimal(match[1]) * 60 + Decimal(match[2] or 0) if match[1] else Decimal(match[3])
        result[minutes] += 1
    return result


def _entry(text: str, labels: str) -> str | None:
    # Preserve a complete labeled line/clause, not a number found elsewhere.
    match = re.search(rf"(?:^|[\n;；]|(?:비용|費用|料金)\s*[:：])\s*(?:{labels})\s*[:：は]\s*([^\n;；]+)", text)
    return match[1] if match else None


def _local_schedule_text(text: str) -> str:
    """Compare clocks in KST; an explicit ISO offset is not another clock.

    Convert complete zoned timestamps, not loose date/time prose. Other loose
    zone annotations are rejected rather than silently interpreted as KST.
    This changes comparison text only, never stored facts or provider output.
    """
    def local(match):
        try:
            value = datetime.fromisoformat(match[0].replace('Z', '+00:00'))
        except ValueError:
            raise AiJobError('ai_schema_error') from None
        return value.astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None).isoformat()
    text = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})', local, text)
    def annotation(match):
        offset = next(v for v in match.groups() if v is not None)
        if offset.replace(':','') != '+0900':
            raise AiJobError('ai_schema_error')
        return ''
    # +09:00, (UTC+09:00), or an offset attached to a localized clock.
    return re.sub(r'\((?:UTC|GMT)?([+-]\d{2}:?\d{2})\)|'
                  r'(?:UTC|GMT)([+-]\d{2}:?\d{2})|'
                  r'(\+\d{2}:?\d{2})(?!\d)', annotation, text)


def _dates_and_times(text: str) -> list[tuple]:
    text = _local_schedule_text(text)
    text = text.translate(str.maketrans({"年": "년", "月": "월", "日": "일", "時": "시", "分": "분"}))
    pattern = (r"(?P<iso>\d{4}-\d{2}-\d{2})|"
               r"(?:(?P<year>\d{4})\s*년\s*)?(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일|"
               r"(?P<colon_hour>\d{1,2}):(?P<colon_minute>\d{2})(?::(?P<colon_second>\d{2}))?|"
               r"(?P<meridiem>오전|오후|午前|午後)?\s*(?P<hour>\d{1,2})\s*시(?!간|間)(?:\s*(?P<minute>\d{1,2})\s*분)?(?:\s*(?P<second>\d{1,2})\s*[초秒])?")
    values = []
    year = None
    for match in re.finditer(pattern, text):
        if match["iso"]:
            year, month, day = (int(x) for x in match["iso"].split("-"))
            values.append(("date", year, month, day))
        elif match["month"]:
            if match["year"]:
                year = int(match["year"])
            values.append(("date", year, int(match["month"]), int(match["day"])))
        else:
            hour = int(match["colon_hour"] or match["hour"])
            minute = int(match["colon_minute"] or match["minute"] or 0)
            second = int(match['colon_second'] or match['second'] or 0)
            if match["meridiem"]:
                hour = hour % 12 + (12 if match["meridiem"] in {"오후", "午後"} else 0)
            if hour > 23 or minute > 59 or second > 59:
                raise AiJobError('ai_schema_error')
            values.append(("time", hour, minute, second) if second else ("time", hour, minute))
    return values


def _require_present(required: Counter, actual: Counter) -> None:
    if required - actual:
        raise AiJobError("ai_schema_error")


def _validate_field(korean: str, japanese: str) -> None:
    # URLs are opaque. Do not NFKC-normalize their path, query or identifiers.
    if Counter(_URL.findall(korean)) - Counter(_URL.findall(japanese)):
        raise AiJobError("ai_schema_error")
    ko, ja = _normal(korean), _normal(japanese)
    _require_present(_amounts(ko, japanese=False), _amounts(ja, japanese=True))
    _require_present(_quantities(ko, japanese=False), _quantities(ja, japanese=True))
    _require_present(_first_come(ko, japanese=False), _first_come(ja, japanese=True))
    _require_present(_durations(ko), _durations(ja))
    for ko_label, ja_label in _PERIOD_ROLES:
        source = _entry(ko, ko_label)
        if source is not None and (expected := _dates_and_times(source)):
            target = _entry(ja, ja_label)
            if target is None or _dates_and_times(target) != expected:
                raise AiJobError("ai_schema_error")
    for ko_label, ja_label in _FEE_ROLES:
        source = _entry(ko, ko_label)
        if source is not None:
            amounts = _amounts(source, japanese=False)
            free = bool(re.search(r"무료|무상", source))
            if amounts or free:
                target = _entry(ja, ja_label)
                if target is None or _amounts(target, japanese=True) != amounts or (
                    free and not re.search(r"無料|無償", target)
                ) or (
                    any(amount > 0 for amount in amounts) and not free and re.search(r"無料|無償", target)
                ):
                    raise AiJobError("ai_schema_error")


def validate_translation_fidelity(title_ko: str, content_ko: str, title_ja: str, content_ja: str) -> None:
    content_ko = normalize_schedule_heading(content_ko, 'ko')
    content_ja = normalize_schedule_heading(content_ja, 'ja')
    for korean, japanese in ((title_ko, title_ja), (content_ko, content_ja)):
        _validate_field(korean, japanese)
    expected = [_HEADERS[h] for h in re.findall(r"(?m)^\s*\[([^\]\n]+)\]", content_ko) if h in _HEADERS]
    actual = [h for h in re.findall(r"(?m)^\s*\[([^\]\n]+)\]", content_ja) if h in _HEADERS.values()]
    if actual != expected:
        raise AiJobError("ai_schema_error")
    if expected and re.match(r"\s*\[", content_ko):
        # A review verdict before the first required section is not content.
        if not content_ja.lstrip().startswith(f"[{expected[0]}]"):
            raise AiJobError("ai_schema_error")
