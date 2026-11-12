"""Small explicit translation checks, not a Japanese semantic interpreter.

Only the supplied Korean text is authoritative. Never repair provider output,
fetch evidence or infer unstated values. Contextual wording remains a review task.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import unicodedata

from ingest.ai_errors import ValidationError, validation_location
from ingest.body_sections import normalize_schedule_heading
from ingest.body_markdown import read_body, inline_text, comparison_text, strong_spans, is_weekday_matrix

_HEADERS = {
    "한 줄 요약": "要約", "대상": "対象", "일정 안내": "日程案内",
    "주요 내용": "主な内容", "신청 방법": "申請方法",
}
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_QUANTITY_UNITS = {False: r"명|인(?!당|분|가구|치|승)|세|회|가족", True: r"名|人(?!分)|歳|回|家族"}
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
    # "1回180分間" is an explicit per-session duration, not a total count.
    # Require a denominator plus a duration unit; exclude 全/計/第 prefixes.
    True: re.compile(r'(?<![\d全計第一二三四五六七八九十百千万])(?:(?P<count>\d+|一)\s*)?回\s*(?:につき|当たり|あたり|ごと(?:に)?|'
                     r'(?(count)(?=\d+(?:\.\d+)?\s*(?:時間|分間))|(?!)))|'
                     r'(?:毎|各)\s*回'),
}
_PER_PERSON = {
    False: re.compile(r'(?P<count>\d+)\s*인\s*당'),
    True: re.compile(r'(?P<count>\d+|一)\s*(?:人|名)\s*(?:当たり|あたり|につき)'),
}


def _per_person(text: str, *, japanese: bool) -> Counter:
    return Counter(1 if m['count'] == '一' else int(m['count'])
                   for m in _PER_PERSON[japanese].finditer(text))


def _session_markers(text: str, *, japanese: bool):
    for match in _PER_SESSION[japanese].finditer(text):
        # Total/ordinal prefixes may be separated by whitespace in source text.
        if japanese and re.search(r'(?:全|計|第)\s*$', text[:match.start()]):
            continue
        yield match


def _per_session(text: str, *, japanese: bool) -> Counter:
    # An implicit single-session denominator is not a total/session ordinal.
    # Explicit other denominators remain data: 2회당 must match 2回当たり.
    return Counter(1 if m['count'] in (None, '一') else int(m['count'])
                   for m in _session_markers(text, japanese=japanese))


def _without_per_session(text: str, *, japanese: bool) -> str:
    # Comparison text only. Never alter stored facts or provider output.
    for match in reversed(list(_session_markers(text, japanese=japanese))):
        text = text[:match.start()] + ' ' + text[match.end():]
    return text


def _quantities(text: str, *, japanese: bool) -> Counter:
    if japanese:
        # Comparison only: retain the exclusive bound and do not match its negation.
        text = re.sub(r'(\d[\d,]*\s*(?:名|人))\s*に満たない(?!わけ|ことはない)', r'\1未満', text)
    text = _without_per_session(text, japanese=japanese)
    text = _PER_PERSON[japanese].sub(' ', text)
    units = _QUANTITY_UNITS[japanese]
    unit_names = {"名": "people", "人": "people", "명": "people", "인": "people", "家族": "families", "가족": "families",
                  "歳": "age", "세": "age", "回": "count", "회": "count"}
    comparisons = {None: None, "이상": "minimum", "以上": "minimum",
                   "이하": "maximum", "以下": "maximum", "미만": "under", "未満": "under",
                   "초과": "over", "超": "over", "내외": "approximately", "정도": "approximately",
                   "程度": "approximately", "前後": "approximately", "ほど": "approximately"}
    suffix = r"以上|以下|未満|程度|前後|ほど|超" if japanese else r"이상|이하|미만|초과|내외|정도"
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
            qualifier = comparisons[match[3]]
            if qualifier is None and re.search(r'(?:약|約)\s*$', text[:match.start()]):
                qualifier = 'approximately'
            quantities[(int(match[1].replace(',', '')), unit_names[match[2]], qualifier)] += 1
    return quantities


def _per_session_allocations(text: str, *, japanese: bool) -> Counter:
    """Bind adjacent explicit quantities to their denominator, not distant digits.

    Limited to quantity runs next to a marker (including 20名・9家族). Other
    prose is left to the existing unit/condition checks and human review.
    """
    units = _QUANTITY_UNITS[japanese]
    suffix = r'以上|以下|未満|超' if japanese else r'이상|이하|미만|초과'
    atom = rf'\d[\d,]*\s*(?:{units})(?:\s*(?:{suffix}))?'
    run = rf'{atom}(?:[·・,、\s-]*{atom})*'
    label = r'(?:の\s*)?(?:(?:定員|参加人数)\s*[:：]?\s*)?' if japanese else r'(?:(?:정원|참가인원)\s*[:：]?\s*)?'
    result = Counter()
    for marker in _session_markers(text, japanese=japanese):
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
               r"(\d[\d,]*)\s*(?:名|人)[（(、\s]*先着(?:順)?") if japanese else r"선착순\s*(\d[\d,]*)\s*(?:명|인(?!당|분))"
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
            raise ValidationError('timestamp', 'invalid') from None
        return value.astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None).isoformat()
    text = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})', local, text)
    def annotation(match):
        offset = next(v for v in match.groups() if v is not None)
        if offset.replace(':','') != '+0900':
            raise ValidationError('timezone', 'unsupported_offset')
        return ''
    # +09:00, (UTC+09:00), or an offset attached to a localized clock.
    return re.sub(r'\((?:UTC|GMT)?([+-]\d{2}:?\d{2})\)|'
                  r'(?:UTC|GMT)([+-]\d{2}:?\d{2})|'
                  r'(\+\d{2}:?\d{2})(?!\d)', annotation, text)


def midnight_closing(prefix: str) -> bool:
    line = prefix.rsplit('\n', 1)[-1]
    return bool(re.search(r'(?:레이저|시설|센터|レーザー|施設|センター)\s*(?:の|의)?\s*(?:운영|이용|개관|運営|稼働|点灯|開館)\s*(?:시간|시間|時間)', line)
                and re.search(r'(?:[01]?\d|2[0-3])(?::[0-5]\d|\s*[시時](?:\s*[0-5]?\d\s*[분分])?)\s*[~～〜–—-]\s*$', line))


def _dates_and_times(text: str, *, known_years: frozenset = frozenset(), facility_range: bool = False) -> list[tuple]:
    text = _local_schedule_text(text)
    # A shared clock unit applies to both endpoints (14~16시), never a duration.
    text = re.sub(r'(?<![\d.:/])(?P<mer>오전|오후|午前|午後)?\s*(?P<a>\d{1,2})\s*(?P<sep>[~～〜–—-])\s*(?P<b>\d{1,2})\s*(?P<unit>[시時])(?!간|間)',
                  lambda m: f'{m["mer"] or ""}{m["a"]}{m["unit"]}{m["sep"]}{m["mer"] or ""}{m["b"]}{m["unit"]}', text)
    text = text.translate(str.maketrans({"年": "년", "月": "월", "日": "일", "時": "시", "分": "분"}))
    pattern = (r"(?P<iso>\d{4}-\d{2}-\d{2})|"
               r"(?<![\w./-])(?P<dot_year>\d{4})\s*\.\s*(?P<dot_month>\d{1,2})\s*\.\s*"
               r"(?P<dot_day>\d{1,2})(?![\d]|\.\d)|"
               r"(?<![\w./-])(?P<short_year>['’]\d{2})\s*\.\s*(?P<short_month>\d{1,2})\s*\.\s*(?P<short_day>\d{1,2})(?!\d|\.\d)|"
               r"(?<![\w.-])(?P<brief_month>\d{1,2})\s*\.\s*(?P<brief_day>\d{1,2})\.?(?=\s*[（(]\s*[월화수목금토일月火水木金土日])|"
               r"(?:(?P<year>\d{4})\s*년\s*)?(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일|"
               r"(?P<colon_hour>\d{1,2}):(?P<colon_minute>\d{2})(?::(?P<colon_second>\d{2}))?|"
               r"(?P<meridiem>오전|오후|午前|午後)?\s*(?P<hour>\d{1,2})\s*시(?!간|間)(?:\s*(?P<minute>\d{1,2})\s*분)?(?:\s*(?P<second>\d{1,2})\s*[초秒])?")
    values = []
    year = next(iter(known_years)) if len(known_years) == 1 else None
    for match in re.finditer(pattern, text):
        if match["iso"]:
            year, month, day = (int(x) for x in match["iso"].split("-"))
            values.append(("date", year, month, day))
        elif match['dot_year']:
            # Version labels are opaque numeric identifiers, not calendars.
            if re.search(r'(?:버전|version|ver\.?|v)\s*[:：]?\s*$', text[:match.start()], re.I):
                continue
            year, month, day = (int(match[k]) for k in ('dot_year', 'dot_month', 'dot_day'))
            values.append(('date', year, month, day))
        elif match['short_year']:
            candidates = {y for y in known_years if y % 100 == int(match['short_year'][1:])}
            if len(candidates) != 1:
                raise ValidationError('date_year', 'ambiguous')
            year = next(iter(candidates))
            values.append(('date', year, int(match['short_month']), int(match['short_day'])))
        elif match['brief_month']:
            values.append(('date', year, int(match['brief_month']), int(match['brief_day'])))
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
            midnight = (hour, minute, second) == (24, 0, 0) and not match['meridiem'] and (
                midnight_closing(text[:match.start()]) or facility_range and bool(values) and values[-1][0] == 'time')
            if (hour > 23 and not midnight) or minute > 59 or second > 59:
                raise ValidationError('clock', 'out_of_range', actual=(hour, minute, second))
            values.append(("time", hour, minute, second) if second else ("time", hour, minute))
        if values and values[-1][0] == 'date':
            _, date_year, month, day = values[-1]
            try:
                # Validate month/day without inventing an omitted year.
                value = datetime(date_year or 2000, month, day)
            except ValueError:
                raise ValidationError('calendar_date', 'out_of_range', actual=values[-1]) from None
            weekday = re.match(r'\.?\s*[（(]\s*([월화수목금토일月火水木金土日])(?:요일|曜日)?\s*[）)]', text[match.end():])
            if weekday and date_year is not None:
                alphabet = '월화수목금토일' if weekday[1] in '월화수목금토일' else '月火水木金土日'
                if alphabet.index(weekday[1]) != value.weekday():
                    raise ValidationError('calendar_weekday', 'mismatch', expected=value.isoweekday(), actual=alphabet.index(weekday[1])+1)
    return values


def _counter_mismatch(rule: str, expected: Counter, actual: Counter) -> ValidationError:
    missing, added = expected - actual, actual - expected
    reason = 'mismatch' if missing and added else 'missing' if missing else 'added'
    keys = dict.fromkeys((*missing, *added))
    return ValidationError(rule, reason,
                          expected=[(key, expected[key]) for key in keys if expected[key]],
                          actual=[(key, actual[key]) for key in keys if actual[key]])


def _require_present(rule: str, required: Counter, actual: Counter) -> None:
    if required - actual:
        raise _counter_mismatch(rule, required, actual)


def _date_year_context(text: str) -> frozenset:
    # Only explicit full calendar years in the authoritative body. No current
    # year/century guessing, URL digits, versions or translated-year authority.
    text = _URL.sub(' ', _normal(comparison_text(text)))
    pattern = r'(?<![\w./-])(\d{4})(?:-\d{2}-\d{2}|\s*년\s*\d{1,2}\s*월|\s*\.\s*\d{1,2}\s*\.\s*\d{1,2})(?!\d|\.\d)'
    return frozenset(int(m[1]) for m in re.finditer(pattern, text)
                     if not re.search(r'(?:버전|version|ver\.?|v)\s*[:：]?\s*$', text[:m.start()], re.I))


@contextmanager
def _advisory(report, **location):
    try:
        with validation_location(**location):
            yield
    except ValidationError as error:
        if report is None:
            raise
        report(error)


def _validate_field(korean: str, japanese: str, *, known_years: frozenset = frozenset(), report=None, field=None) -> None:
    korean, japanese = comparison_text(korean), comparison_text(japanese)
    # URLs are opaque. Do not NFKC-normalize their path, query or identifiers.
    with _advisory(report, field=field):
        if Counter(_URL.findall(korean)) - Counter(_URL.findall(japanese)):
            raise ValidationError('official_link', 'missing')
    ko, ja = _normal(korean), _normal(japanese)
    with _advisory(report, field=field):
        _require_present('fee_amount', _amounts(ko, japanese=False), _amounts(ja, japanese=True))
    with _advisory(report, field=field):
        _require_present('per_session', _per_session(ko, japanese=False), _per_session(ja, japanese=True))
    with _advisory(report, field=field):
        _require_present('per_person', _per_person(ko, japanese=False), _per_person(ja, japanese=True))
    with _advisory(report, field=field):
        _require_present('quantity', _quantities(ko, japanese=False), _quantities(ja, japanese=True))
    with _advisory(report, field=field):
        _require_present('first_come_quantity', _first_come(ko, japanese=False), _first_come(ja, japanese=True))
    with _advisory(report, field=field):
        _require_present('duration_minutes', _durations(ko), _durations(ja))
    for role, (ko_label, ja_label) in zip(('application', 'operation', 'meeting', 'deadline'), _PERIOD_ROLES):
        source = _entry(ko, ko_label)
        if source is not None and (expected := _dates_and_times(source, known_years=known_years)):
            target = _entry(ja, ja_label)
            actual = _dates_and_times(target, known_years=known_years) if target is not None else []
            with _advisory(report, field=field):
                if actual != expected:
                    raise ValidationError('period_date_time', 'missing' if not actual else 'mismatch',
                                          location={'period_role': role}, expected=expected, actual=actual)
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
                    with _advisory(report, field=field):
                        raise ValidationError('fee_role', 'missing_or_mismatched', expected=list(amounts), actual=list(_amounts(target or '', japanese=True)))


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
            raise ValidationError('calendar_date', 'out_of_range', actual=('date',year,month,day)) from None
        return f'{year}년 {month}월 {day}일'
    text = re.sub(r'\b('+'|'.join(months)+r')\s+(\d{1,2}),\s*(\d{4})\b', english_date, text)
    def mongolian_date(match):
        year, month, day = map(int, match.groups())
        try:
            datetime(year, month, day)
        except ValueError:
            raise ValidationError('calendar_date', 'out_of_range', actual=('date',year,month,day)) from None
        return f'{year}년 {month}월 {day}일'
    text = re.sub(r'\b(\d{4})\s+оны\s+(\d{1,2})-р\s+сарын\s+(\d{1,2})\b', mongolian_date, text)
    def english_clock_range(match):
        values = []
        for hour, minute in ((match[1],match[2]), (match[3],match[4])):
            hour, minute = int(hour), int(minute)
            if not 1 <= hour <= 12 or not 0 <= minute <= 59:
                raise ValidationError('clock', 'out_of_range', actual=(hour,minute))
            hour = hour % 12 + (12 if match[5] == 'PM' else 0)
            values.append(f'{hour}시{minute:02}분')
        return '~'.join(values)
    text = re.sub(r'(?<!\d)(\d{1,2}):(\d{2})\s*[~～〜–—-]\s*'
                  r'(\d{1,2}):(\d{2})\s*(AM|PM)\b', english_clock_range, text)
    return re.sub(r'(\d[\d,]*)\s*(?:people\b|хүн\b|人)', r'\1명', text)


def _validate_cell(korean: str, japanese: str, *, known_years: frozenset = frozenset()) -> None:
    raw_ko, raw_ja = inline_text(korean), inline_text(japanese)
    # Check opaque URLs before NFKC/source notation normalization.
    known_years = known_years or _date_year_context(raw_ko)
    _validate_field(raw_ko, raw_ja, known_years=known_years)
    ko, ja = _normal(raw_ko), _normal(raw_ja)
    source_id, source_text = _cell_ordinal(ko)
    target_id, target_text = _cell_ordinal(ja)
    if source_id != target_id:
        raise ValidationError('session_number', 'mismatch', expected=source_id, actual=target_id)
    ko, ja = _explicit_source_cell(source_text), target_text
    _validate_field(ko, ja, known_years=known_years)
    # Within one cell/item a date or time cannot be recovered from another row.
    expected = _dates_and_times(_normal(ko), known_years=known_years)
    actual = _dates_and_times(_normal(ja), known_years=known_years)
    if expected != actual:
        mismatch = next((i for i, pair in enumerate(zip(expected, actual)) if pair[0] != pair[1]),
                        min(len(expected), len(actual)))
        expected_value = expected[mismatch] if mismatch < len(expected) else None
        actual_value = actual[mismatch] if mismatch < len(actual) else None
        reason = 'added' if expected_value is None else 'missing' if actual_value is None else 'mismatch'
        raise ValidationError('cell_date_time', reason, expected=expected_value, actual=actual_value)
    for rule, check in (('fee_amount', _amounts), ('quantity', _quantities),
                        ('per_session', _per_session), ('per_person', _per_person)):
        expected = check(_normal(ko), japanese=False)
        actual = check(_normal(ja), japanese=True)
        if expected != actual:
            raise _counter_mismatch(rule, expected, actual)
    source_allocation = _per_session_allocations(_normal(ko), japanese=False)
    target_allocation = _per_session_allocations(_normal(ja), japanese=True)
    if source_allocation and target_allocation and source_allocation != target_allocation:
        raise _counter_mismatch('session_allocation', source_allocation, target_allocation)
    # Class IDs/visa numbers without a recognized amount/date/unit still belong
    # to this cell. This is a bounded numeric check, not meaning interpretation.
    if not (_dates_and_times(ko, known_years=known_years) or _amounts(ko, japanese=False) or _quantities(ko, japanese=False) or _durations(ko)):
        from ingest.place_ja_glossary import numeric_name_views
        ko_digits, ja_digits = numeric_name_views(ko, ja)
        source_digits = _PER_PERSON[False].sub(' ', _without_per_session(ko_digits, japanese=False))
        target_digits = _PER_PERSON[True].sub(' ', _without_per_session(ja_digits, japanese=True))
        if Counter(re.findall(r'\d+', source_digits)) != Counter(re.findall(r'\d+', target_digits)):
            raise ValidationError('opaque_numeric_identifier', 'mismatch')
    for source, target in ((r'필수|의무', r'必須|必要|義務'),
                           (r'(?:신청|참가|참여|예약)\s*(?:은|는|이|가)?\s*불가|금지',
                            r'不可|禁止|できません|できない|できなく')):
        if re.search(source, ko) and not re.search(target, ja):
            raise ValidationError('participation_constraint', 'missing')


def _validate_markdown(korean: str, japanese: str, *, report=None) -> None:
    ko, ja = read_body(korean), read_body(japanese)
    known_years = _date_year_context(korean)
    with _advisory(report, field='body'):
        if len(ko.tables) != len(ja.tables):
            raise ValidationError('table_count', 'mismatch', expected=len(ko.tables), actual=len(ja.tables))
    with _advisory(report, field='body'):
        if len(ko.items) != len(ja.items):
            raise ValidationError('list_item_count', 'mismatch', expected=len(ko.items), actual=len(ja.items))
    for table, (source, target) in enumerate(zip(ko.tables, ja.tables), 1):
        expected_shape = (source.section, len(source.headers), len(source.rows))
        actual_shape = (target.section, len(target.headers), len(target.rows))
        if expected_shape != actual_shape:
            with _advisory(report, field='body', table=table):
                raise ValidationError('table_shape', 'mismatch', expected=expected_shape, actual=actual_shape)
            continue
        for column, (source_header, target_header) in enumerate(zip(source.headers, target.headers), 1):
            with _advisory(report, field='body', table=table, row=0, column=column):
                _validate_role_label(source_header, target_header)
        for row, (source_row, target_row) in enumerate(zip(source.rows, target.rows), 1):
            for column, (source_cell, target_cell) in enumerate(zip(source_row, target_row), 1):
                with _advisory(report, field='body', table=table, row=row, column=column):
                    if column == 1:
                        _validate_role_label(source_cell, target_cell)
                    if is_weekday_matrix(source.headers):
                        _validate_weekday_cell(source_cell, target_cell)
                    _validate_cell(source_cell, target_cell, known_years=known_years)
    for index, (source, target) in enumerate(zip(ko.items, ja.items), 1):
        with _advisory(report, field='body', item=index):
            if (source.section, source.indent, source.number) != (target.section, target.indent, target.number):
                raise ValidationError('list_item_shape', 'mismatch')
            _validate_cell(source.text, target.text, known_years=known_years)
    source_bold, target_bold = strong_spans(korean), strong_spans(japanese)
    with _advisory(report, field='body'):
        if source_bold and not target_bold:
            raise ValidationError('emphasis', 'missing')
    if len(source_bold) == len(target_bold):
        for source, target in zip(source_bold, target_bold):
            with _advisory(report, field='body'):
                _validate_cell(source, target, known_years=known_years)
    # Recognized emphasized fact labels must keep their translated emphasis.
    # Arbitrary natural-language emphasis remains a model/human review task.
    for ko_label, ja_label in (*_PERIOD_ROLES, *_FEE_ROLES):
        if any(re.search(ko_label, span) for span in source_bold) and not any(
                re.search(ja_label, span) for span in target_bold):
            with _advisory(report, field='body'):
                raise ValidationError('emphasized_fact_label', 'missing')


def _validate_weekday_cell(korean: str, japanese: str) -> None:
    """Preserve known empty positions and explicit per-session languages.

    An empty source cell cannot become a new cancellation/absence claim.
    This is a bounded matrix check, not free-text language interpretation.
    """
    source, target = inline_text(korean).strip(), inline_text(japanese).strip()
    empty = {'', '—', '–', '-'}
    if source in empty or target in empty:
        if source not in empty or target not in empty:
            raise ValidationError('weekday_cell', 'missing' if target in empty else 'added')
    languages = ((r'일본어|日本語', r'日本語'), (r'중국어|中国語', r'中国語'),
                 (r'영어|英語', r'英語'), (r'한국어|韓国語', r'韓国語'))
    for ko_pattern, ja_pattern in languages:
        if len(re.findall(ko_pattern, source)) != len(re.findall(ja_pattern, target)):
            raise ValidationError('session_language', 'mismatch', expected=len(re.findall(ko_pattern, source)), actual=len(re.findall(ja_pattern, target)))


def _validate_role_label(korean: str, japanese: str) -> None:
    source = inline_text(korean).strip()
    day = re.fullmatch(r'([월화수목금토일])(?:요일)?', source)
    if day:
        target = '月火水木金土日'['월화수목금토일'.index(day[1])]
        if not re.fullmatch(target+r'(?:曜日)?', inline_text(japanese).strip()):
            raise ValidationError('weekday_label', 'mismatch', expected='월화수목금토일'.index(day[1])+1)
    for ko_label, ja_label in (*_PERIOD_ROLES, *_FEE_ROLES):
        if re.fullmatch(r'(?:' + ko_label + r')(?:\s*\([^)]*\))?', inline_text(korean)):
            if not re.fullmatch(r'(?:' + ja_label + r')(?:\s*[（(][^）)]*[）)])?', inline_text(japanese)):
                raise ValidationError('table_role_label', 'mismatch')


def validate_translation_fidelity(title_ko: str, content_ko: str, title_ja: str, content_ja: str, *, report=None) -> None:
    content_ko = normalize_schedule_heading(content_ko, 'ko')
    content_ja = normalize_schedule_heading(content_ja, 'ja')
    with _advisory(report, field='title'):
        _validate_field(title_ko, title_ja, known_years=_date_year_context(title_ko), report=report, field='title')
    with _advisory(report, field='body'):
        # Structured cells are checked before the body-wide inventory.
        _validate_markdown(content_ko, content_ja, report=report)
    with _advisory(report, field='body'):
        _validate_field(content_ko, content_ja, known_years=_date_year_context(content_ko), report=report, field='body')
    expected = [_HEADERS[h] for h in re.findall(r"(?m)^\s*\[([^\]\n]+)\]", content_ko) if h in _HEADERS]
    actual = [h for h in re.findall(r"(?m)^\s*\[([^\]\n]+)\]", content_ja) if h in _HEADERS.values()]
    with _advisory(report):
        if actual != expected:
            raise ValidationError('translated_sections', 'missing_added_or_reordered')
    if expected and re.match(r"\s*\[", content_ko):
        # A review verdict before the first required section is not content.
        if not content_ja.lstrip().startswith(f"[{expected[0]}]"):
            with _advisory(report):
                raise ValidationError('translated_sections', 'unexpected_preamble')
