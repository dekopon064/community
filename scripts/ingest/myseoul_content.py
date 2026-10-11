"""Bounded checks for explicit reviewed quantities and schedule lines.

No model calls, calendar expansion, source lookup or inferred sessions.
"""
from __future__ import annotations

import re
from datetime import date
from ingest.ai_errors import AiJobError
from ingest.myseoul_ai_support import schedule_values
from ingest.translation_validation import _dates_and_times, _entry, _quantities, _amounts


def schedule_lines(f: dict) -> list[str]:
    # Explicit structured sessions take precedence over the current description.
    if f.get('session_evidence'):
        return list(f['session_evidence'])
    lines = []
    for line in f.get('description', '').splitlines():
        line = line.strip()
        if (not line or len(line) > 1500 or
                re.search(r'신청|접수|모집|발표|마감', line)):
            continue
        if (re.search(r'일정|일시|회차|교육일|수업일|총\s*\d+\s*회', line)
                and any(schedule_values(line).values())):
            if line not in lines:
                lines.append(line)
    return lines


def optional_period_section(content: str) -> str:
    match = re.search(r'(?ms)^\s*\[기간·상태\][ \t]*(.*?)(?=^\s*\[|\Z)', content)
    return match[1].strip() if match else ''


def _operation_date_bounds(f: dict) -> list[tuple[date, date]]:
    bounds = []
    for period in f.get('periods', {}).get('operation', []):
        endpoints = period.get('endpoints', [])
        if period.get('status') != 'ok' or len(endpoints) != 2:
            continue
        try:
            start, end = (date.fromisoformat(endpoint['value'][:10]) for endpoint in endpoints)
        except (KeyError, TypeError, ValueError):
            continue
        if start <= end:
            bounds.append((start, end))
    return bounds


def _unique_operation_year(month: int, day: int, bounds: list[tuple[date, date]]) -> int | None:
    # Validate an existing month/day only; do not add years to facts or output.
    years = set()
    for start, end in bounds:
        for year in range(start.year, end.year + 1):
            try:
                occurrence = date(year, month, day)
            except ValueError:
                continue
            if start <= occurrence <= end:
                years.add(year)
                if len(years) > 1:
                    return None
    return next(iter(years)) if len(years) == 1 else None


def _validate_schedule_years(line: str, evidence: list[str], f: dict, expected_years: set) -> None:
    dates = [value for text in evidence for value in _dates_and_times(text) if value[0] == 'date']
    bounds = _operation_date_bounds(f)
    verified_years = set(expected_years)
    for value in _dates_and_times(line):
        if value[0] != 'date' or value[1] is None:
            continue
        _, year, month, day = value
        matches = [value for value in dates if value[2:] == (month, day)]
        if not matches:
            raise AiJobError('ai_schema_error')
        explicit = {value[1] for value in matches if value[1] is not None}
        # Explicit evidence wins. A period cannot override a conflicting year.
        allowed = explicit or {_unique_operation_year(month, day, bounds)}
        if year not in allowed:
            raise AiJobError('ai_schema_error')
        try:
            occurrence = date(year, month, day)
        except ValueError:
            raise AiJobError('ai_schema_error') from None
        if bounds and not any(start <= occurrence <= end for start, end in bounds):
            raise AiJobError('ai_schema_error')
        verified_years.add(year)
    if not schedule_values(line)['years'].issubset(verified_years):
        raise AiJobError('ai_schema_error')


def validate_summary_period(summary: str, canonical: str, f: dict) -> None:
    # Detect altered explicit ranges by role, not by a shared number bag.
    for labels in (r'신청\s*기간', r'진행\s*기간|운영\s*기간|개최\s*기간'):
        generated = _entry(summary, labels)
        expected = _entry(canonical, labels)
        if generated and expected:
            actual_values = _dates_and_times(generated)
            expected_values = _dates_and_times(expected)
            # Omitted endpoint years are permitted here; canonical output keeps
            # the reviewed year. An explicitly different year remains a conflict.
            compatible = len(actual_values) == len(expected_values) and all(
                a == b or a[0] == b[0] == 'date' and a[1] is None and a[2:] == b[2:]
                for a, b in zip(actual_values, expected_values))
            if actual_values and not compatible:
                raise AiJobError('ai_schema_error')
    evidence = schedule_lines(f) + f.get('meeting_evidence', [])
    expected = schedule_values('\n'.join(evidence))
    for line in summary.splitlines():
        if re.search(r'일정|회차|집결|실제\s*수업|총\s*\d+\s*회', line):
            actual = schedule_values(line)
            if any(not values.issubset(expected[key]) for key, values in actual.items() if key != 'years'):
                raise AiJobError('ai_schema_error')
            _validate_schedule_years(line, evidence, f, expected['years'])


def participation_constraints(f: dict) -> list[str]:
    values = [*f.get('conditions', []), *f.get('age', []), *f.get('companion', []),
              *f.get('language', []), f.get('residence', ''), f.get('qualification_note', '')]
    # Only an explicit promotional benefit percentage without eligibility words
    # is optional. Mixed participation/benefit statements remain protected.
    result = []
    for value in values:
        if (re.search(r'(?:효율|생산성|역량|능력).{0,30}\d+(?:\.\d+)?\s*%.{0,30}(?:향상|강화|올|높|개선)', value)
                and not re.search(r'신청|대상|참가|자격|비자|국적|거주|이상|이하|\d+\s*(?:명|세)', value)):
            continue
        if value.strip() and value not in result:
            result.append(value)
    return result


def validate_participant_quantities(f: dict, main: str) -> None:
    required = _quantities('\n'.join([f['target'], *participation_constraints(f),
                                      *f.get('capacity_raw', [])]), japanese=False)
    actual = _quantities(f['target'] + '\n' + main, japanese=False)
    if required.keys() - actual.keys():
        raise AiJobError('ai_schema_error')
    # Additional quantities in generated prose must also occur in current data.
    source = '\n'.join([f.get('description', ''), f['target'],
        *participation_constraints(f), *f.get('capacity_raw', []), *schedule_lines(f)])
    if actual.keys() - _quantities(source, japanese=False).keys():
        raise AiJobError('ai_schema_error')


_FEE_VALUE = re.compile(
    r'(?P<label>수강료|입장료|재료비|기타\s*비용)\s*(?:[는은이가를을]\s*|[:：]\s*)?'
    r'(?:별도로\s*)?(?P<per_person>1인당\s*)?'
    r'(?P<value>무료|무상|\d[\d,]*(?:\.\d+)?\s*(?:만|천)?\s*(?:원|엔|円|달러|USD))')


def validate_summary_fees(main: str, activity: str) -> None:
    for label in ('수강료', '입장료', '재료비', '기타 비용'):
        generated, expected = _entry(main, label), _entry(activity, label)
        if generated is not None:
            generated = re.split(r'(?:수강료|입장료|재료비|기타\s*비용)\s*(?:[:：]|는|은)',
                generated, maxsplit=1)[0]
            if expected is None or _amounts(generated, japanese=False) != _amounts(expected, japanese=False):
                raise AiJobError('ai_schema_error')
            if bool(re.search(r'무료|무상', generated)) != bool(re.search(r'무료|무상', expected)):
                raise AiJobError('ai_schema_error')
    # Natural prose also carries a cost role; validate before removing repeats.
    for match in _FEE_VALUE.finditer(main):
        label = '기타 비용' if match['label'].startswith('기타') else match['label']
        expected = _entry(activity, label)
        value = match['value']
        if (expected is None or _amounts(value, japanese=False) != _amounts(expected, japanese=False)
                or bool(re.search(r'무료|무상', value)) != bool(re.search(r'무료|무상', expected))):
            raise AiJobError('ai_schema_error')


def _fee_sentences(text: str):
    for line in text.splitlines(keepends=True):
        yield from re.split(r'(?<=[.!?。])(?=\s|$)', line)


def _simple_fee_sentence(sentence: str) -> bool:
    text = re.sub(r'^\s*비용\s*[:：]\s*', '', sentence.strip())
    matches = list(_FEE_VALUE.finditer(text))
    if not matches or any(match['per_person'] for match in matches):
        return False
    # A bounded grammar for fee-only statements. Any activity, unit qualifier,
    # alternative, discount/refund/payment condition stays in the residue.
    residue = _FEE_VALUE.sub('', text)
    return re.fullmatch(
        r'[\s,;；.!?。]*(?:(?:입니다|이다|이며|이고|및|와|과|이|가|는|은|별도로|별도|있습니다|있다)'
        r'[\s,;；.!?。]*)*', residue) is not None


def deduplicate_summary_fees(main: str, activity: str) -> str:
    """Keep authoritative fee rows, removing only equivalent fee-only prose.

    Mixed activity/discount/refund sentences stay intact. Reviewed fee rows keep
    all their qualifiers. No inferred totals or changes to reviewed facts.
    """
    validate_summary_fees(main, activity)
    return ''.join(sentence for sentence in _fee_sentences(main)
                   if not _simple_fee_sentence(sentence)).strip()


def validate_assembled_fees(content: str, activity: str, *, canonical_block: str | None = None) -> None:
    """Exclude the one reviewed block; reject recognizable leftover simple fees.

    This checks all public sections, including a fee-only summary. Conditions
    that cannot be separated safely are preserved, not classified as duplicates.
    """
    block = canonical_block if canonical_block is not None else activity
    if content.count(block) != 1:
        raise AiJobError('ai_schema_error')
    generated = content.replace(block, '', 1)
    validate_summary_fees(generated, activity)
    if any(_simple_fee_sentence(sentence) for sentence in _fee_sentences(generated)):
        raise AiJobError('ai_schema_error')
