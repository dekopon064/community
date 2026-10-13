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
from ingest.body_markdown import read_body, inline_text, comparison_text, strong_spans

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
    (r"진행\s*기간|개최\s*기간|운영\s*기간", r"(?:実施|開催|運営|実施・開催)期間"),
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


_PER_SESSION = {
    False: re.compile(r'(?<![\d제])(?:(?P<count>\d+)\s*)?회(?:차)?\s*(?:당|마다)|'
                      r'(?:매|각)\s*회(?:차)?(?![가-힣])'),
    True: re.compile(r'(?<![\d第一二三四五六七八九十百千万])(?:(?P<count>\d+|一)\s*)?回\s*(?:につき|当たり|あたり|ごと(?:に)?)|'
                     r'(?:毎|各)\s*回'),
}


def _per_session(text: str, *, japanese: bool) -> Counter:
    # An implicit single-session denominator is not a total/session ordinal.
    # Explicit other denominators remain data: 2회당 must match 2回当たり.
    return Counter(1 if m['count'] in (None, '一') else int(m['count'])
                   for m in _PER_SESSION[japanese].finditer(text))


def _without_per_session(text: str, *, japanese: bool) -> str:
    # Comparison text only. Never alter stored facts or provider output.
    return _PER_SESSION[japanese].sub(' ', text)


def _quantities(text: str, *, japanese: bool) -> Counter:
    text = _without_per_session(text, japanese=japanese)
    units = r"名|人|歳|回|家族" if japanese else r"명|세|회|가족"
    unit_names = {"名": "people", "人": "people", "명": "people", "家族": "families", "가족": "families",
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


def _per_session_allocations(text: str, *, japanese: bool) -> Counter:
    """Bind adjacent explicit quantities to their denominator, not distant digits.

    Limited to quantity runs next to a marker (including 20名・9家族). Other
    prose is left to the existing unit/condition checks and human review.
    """
    units = r'名|人|歳|回|家族' if japanese else r'명|세|회|가족'
    suffix = r'以上|以下|未満|超' if japanese else r'이상|이하|미만|초과'
    atom = rf'\d[\d,]*\s*(?:{units})(?:\s*(?:{suffix}))?'
    run = rf'{atom}(?:[·・,、\s-]*{atom})*'
    label = r'(?:の\s*)?(?:(?:定員|参加人数)\s*[:：]?\s*)?' if japanese else r'(?:(?:정원|참가인원)\s*[:：]?\s*)?'
    result = Counter()
    for marker in _PER_SESSION[japanese].finditer(text):
        denominator = 1 if marker['count'] in (None, '一') else int(marker['count'])
        after = re.match(rf'\s*[:：]?\s*{label}(?P<quantities>{run})', text[marker.end():])
        before = re.search(rf'(?P<quantities>{run})\s*[（(]?\s*$', text[:marker.start()]) if not after else None
        adjacent = after or before
        if adjacent:
            for quantity, count in _quantities(adjacent['quantities'], japanese=japanese).items():
                result[(denominator, *quantity)] += count
    return result


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
    text = comparison_text(text)
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
    korean, japanese = comparison_text(korean), comparison_text(japanese)
    # URLs are opaque. Do not NFKC-normalize their path, query or identifiers.
    if Counter(_URL.findall(korean)) - Counter(_URL.findall(japanese)):
        raise AiJobError("ai_schema_error")
    ko, ja = _normal(korean), _normal(japanese)
    _require_present(_amounts(ko, japanese=False), _amounts(ja, japanese=True))
    _require_present(_per_session(ko, japanese=False), _per_session(ja, japanese=True))
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


def _cell_ordinal(text: str) -> tuple[int | None, str]:
    # A leading session label, separate from a total count such as '총 3회'.
    patterns = (r'^(?:제|第)?(\d+)\s*(?:회차|차|次)(?![A-Za-z가-힣])',
                r'^(?:제|第)(\d+)\s*(?:회|回)',
                r'^(\d+)\s*(?:회|回)(?=\s*[:：]|\s*$)',
                r'^(\d+)(?:st|nd|rd|th)\b', r'^(\d+)-р\s*ээлж\b')
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            return int(match[1]), text[match.end():]
    match = re.match(r'^第([一二三四五六七八九十])场', text)
    if match:
        return '一二三四五六七八九十'.index(match[1]) + 1, text[match.end():]
    return None, text


def _explicit_source_cell(text: str) -> str:
    """Comparison only: explicit multilingual dates/units in reviewed records.

    No date lookup, omitted-year/calendar expansion or stored-text rewriting.
    Unknown expressions remain subject to the existing strict comparisons.
    """
    urls = list(_URL.finditer(text))
    if urls:
        # Query/path bytes may resemble a date or unit; they are opaque data.
        parts, start = [], 0
        for url in urls:
            parts.extend((_explicit_source_cell(text[start:url.start()]), url[0]))
            start = url.end()
        parts.append(_explicit_source_cell(text[start:]))
        return ''.join(parts)
    months = {name: number for number, name in enumerate((
        'January','February','March','April','May','June','July','August',
        'September','October','November','December'), 1)}
    def english_date(match):
        year, month, day = int(match[3]), months[match[1]], int(match[2])
        try:
            datetime(year, month, day)
        except ValueError:
            raise AiJobError('ai_schema_error') from None
        return f'{year}년 {month}월 {day}일'
    text = re.sub(r'\b('+'|'.join(months)+r')\s+(\d{1,2}),\s*(\d{4})\b', english_date, text)
    def mongolian_date(match):
        year, month, day = map(int, match.groups())
        try:
            datetime(year, month, day)
        except ValueError:
            raise AiJobError('ai_schema_error') from None
        return f'{year}년 {month}월 {day}일'
    text = re.sub(r'\b(\d{4})\s+оны\s+(\d{1,2})-р\s+сарын\s+(\d{1,2})\b', mongolian_date, text)
    def english_clock_range(match):
        values = []
        for hour, minute in ((match[1],match[2]), (match[3],match[4])):
            hour, minute = int(hour), int(minute)
            if not 1 <= hour <= 12 or not 0 <= minute <= 59:
                raise AiJobError('ai_schema_error')
            hour = hour % 12 + (12 if match[5] == 'PM' else 0)
            values.append(f'{hour}시{minute:02}분')
        return '~'.join(values)
    text = re.sub(r'(?<!\d)(\d{1,2}):(\d{2})\s*[~～〜–—-]\s*'
                  r'(\d{1,2}):(\d{2})\s*(AM|PM)\b', english_clock_range, text)
    return re.sub(r'(\d[\d,]*)\s*(?:people\b|хүн\b|人)', r'\1명', text)


def _validate_cell(korean: str, japanese: str) -> None:
    raw_ko, raw_ja = inline_text(korean), inline_text(japanese)
    # Check opaque URLs before NFKC/source notation normalization.
    _validate_field(raw_ko, raw_ja)
    ko, ja = _normal(raw_ko), _normal(raw_ja)
    source_id, source_text = _cell_ordinal(ko)
    target_id, target_text = _cell_ordinal(ja)
    if source_id != target_id:
        raise AiJobError('ai_schema_error')
    ko, ja = _explicit_source_cell(source_text), target_text
    _validate_field(ko, ja)
    # Within one cell/item a date or time cannot be recovered from another row.
    if _dates_and_times(_normal(ko)) != _dates_and_times(_normal(ja)):
        raise AiJobError('ai_schema_error')
    for check in (_amounts, _quantities, _per_session):
        if check(_normal(ko), japanese=False) != check(_normal(ja), japanese=True):
            raise AiJobError('ai_schema_error')
    source_allocation = _per_session_allocations(_normal(ko), japanese=False)
    target_allocation = _per_session_allocations(_normal(ja), japanese=True)
    if source_allocation and target_allocation and source_allocation != target_allocation:
        raise AiJobError('ai_schema_error')
    # Class IDs/visa numbers without a recognized amount/date/unit still belong
    # to this cell. This is a bounded numeric check, not meaning interpretation.
    if not (_dates_and_times(ko) or _amounts(ko, japanese=False) or _quantities(ko, japanese=False) or _durations(ko)):
        source_digits = _without_per_session(ko, japanese=False)
        target_digits = _without_per_session(ja, japanese=True)
        if Counter(re.findall(r'\d+', source_digits)) != Counter(re.findall(r'\d+', target_digits)):
            raise AiJobError('ai_schema_error')
    for source, target in ((r'필수|의무', r'必須|必要|義務'),
                           (r'(?:신청|참가|참여|예약)\s*(?:은|는|이|가)?\s*불가|금지',
                            r'不可|禁止|できません|できない|できなく')):
        if re.search(source, ko) and not re.search(target, ja):
            raise AiJobError('ai_schema_error')


def _validate_markdown(korean: str, japanese: str) -> None:
    ko, ja = read_body(korean), read_body(japanese)
    if len(ko.tables) != len(ja.tables) or len(ko.items) != len(ja.items):
        raise AiJobError('ai_schema_error')
    for source, target in zip(ko.tables, ja.tables):
        if (source.section != target.section or len(source.headers) != len(target.headers)
                or len(source.rows) != len(target.rows)):
            raise AiJobError('ai_schema_error')
        for source_header, target_header in zip(source.headers, target.headers):
            _validate_role_label(source_header, target_header)
        for source_row, target_row in zip(source.rows, target.rows):
            _validate_role_label(source_row[0], target_row[0])
            for source_cell, target_cell in zip(source_row, target_row):
                _validate_cell(source_cell, target_cell)
    for source, target in zip(ko.items, ja.items):
        if (source.section, source.indent, source.number) != (target.section, target.indent, target.number):
            raise AiJobError('ai_schema_error')
        _validate_cell(source.text, target.text)
    source_bold, target_bold = strong_spans(korean), strong_spans(japanese)
    if source_bold and not target_bold:
        raise AiJobError('ai_schema_error')
    if len(source_bold) == len(target_bold):
        for source, target in zip(source_bold, target_bold):
            _validate_cell(source, target)
    # Recognized emphasized fact labels must keep their translated emphasis.
    # Arbitrary natural-language emphasis remains a model/human review task.
    for ko_label, ja_label in (*_PERIOD_ROLES, *_FEE_ROLES):
        if any(re.search(ko_label, span) for span in source_bold) and not any(
                re.search(ja_label, span) for span in target_bold):
            raise AiJobError('ai_schema_error')


def _validate_role_label(korean: str, japanese: str) -> None:
    for ko_label, ja_label in (*_PERIOD_ROLES, *_FEE_ROLES):
        if re.fullmatch(r'(?:' + ko_label + r')(?:\s*\([^)]*\))?', inline_text(korean)):
            if not re.fullmatch(r'(?:' + ja_label + r')(?:\s*[（(][^）)]*[）)])?', inline_text(japanese)):
                raise AiJobError('ai_schema_error')


def validate_translation_fidelity(title_ko: str, content_ko: str, title_ja: str, content_ja: str) -> None:
    content_ko = normalize_schedule_heading(content_ko, 'ko')
    content_ja = normalize_schedule_heading(content_ja, 'ja')
    for korean, japanese in ((title_ko, title_ja), (content_ko, content_ja)):
        _validate_field(korean, japanese)
    _validate_markdown(content_ko, content_ja)
    expected = [_HEADERS[h] for h in re.findall(r"(?m)^\s*\[([^\]\n]+)\]", content_ko) if h in _HEADERS]
    actual = [h for h in re.findall(r"(?m)^\s*\[([^\]\n]+)\]", content_ja) if h in _HEADERS.values()]
    if actual != expected:
        raise AiJobError("ai_schema_error")
    if expected and re.match(r"\s*\[", content_ko):
        # A review verdict before the first required section is not content.
        if not content_ja.lstrip().startswith(f"[{expected[0]}]"):
            raise AiJobError("ai_schema_error")
