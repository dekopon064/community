"""Pure proposals for current Seoul review facts; never performs a save or a claim."""
from __future__ import annotations

import copy
import re
from datetime import datetime
from types import SimpleNamespace

from ingest.content_filters import extract_filter_facts, missing_filters
from ingest.program_scope import extract_program_facts
from ingest.seoul_evidence import _RANGE, _clean, period_days


def same_period_supported(facts: dict) -> bool:
    """Preview only. SQL independently proves the same current facts under locks."""
    if 'body_period_needs_confirmation' not in facts['missing'] or set(facts['conflicts']) & {
            'body_period_needs_confirmation', 'body_api_period_conflict', 'date_weekday_conflict',
            'invalid_body_date', 'period_order_conflict'}:
        return False
    if any(x['status'] != 'ok' for x in facts['periods'].values()):
        return False
    seen = []
    for line in facts['description'].splitlines():
        label = re.match(r'^(접수기간|신청기간|모집기간|운영기간|진행기간)\s*[:：]\s*(.*)$', _clean(line))
        if not label:
            continue
        statement = label[2].strip()
        days, issue = period_days(statement)
        match = _RANGE.match(statement)
        if issue or not match:
            return False
        suffix = statement[match.end():].strip()
        clock = re.fullmatch(r'([0-9]{1,2}):([0-5][0-9])', suffix) if suffix else None
        if suffix and (not clock or int(clock[1]) > 23):
            return False
        role = 'SVCOPN' if label[1] in ('운영기간', '진행기간') else 'RCPT'
        for key, day in zip(('BGNDT', 'ENDDT'), days):
            ep = facts['periods'][role + key]
            if ep['precision'] == 'day':
                actual = ep['value']
            else:
                from ingest.content_filters import KST
                actual = datetime.fromisoformat(ep['value']).astimezone(KST).date().isoformat()
            if actual != day:
                return False
        if clock:
            ep = facts['periods'][role + 'ENDDT']
            from ingest.content_filters import KST
            if ep['precision'] != 'second' or datetime.fromisoformat(ep['value']).astimezone(KST).strftime('%H:%M:%S') != f'{int(clock[1]):02d}:{clock[2]}:00':
                return False
        seen.append(statement)
    return bool(seen and facts['period_evidence'] and all(x in seen for x in facts['period_evidence']))


def propose_connections(detail: dict, *, provider_fields=None, tables=(), operator_fields=()) -> dict:
    """Only fill unknown, non-operator fields. Known values are never refreshed.

    Callers must bind retained provider/table context to the current description
    and revision. Output is a preview, not authority to bypass normal save fences.
    """
    facts = copy.deepcopy(detail['facts'])
    info = detail['filterInfo']
    result = {'facts_patch': {}, 'filters_patch': {}, 'resolve': [], 'evidence': {},
              'held': [], 'revision': detail['revision'], 'version': detail['version'],
              'factsVersion': detail['factsVersion'], 'filterVersion': info['filterVersion']}
    if detail['status'] != 'open' or detail['aiStatus'] in ('claimed', 'completed') or any(
            x in detail['result']['reasons'] for x in ('ai_recheck_requested', 'restored_review_pending')):
        result['held'].append('review_not_editable')
        return result
    payload = {'source_id': 'seoul_reservation', 'title': '', 'program_text': facts['description'],
               'plain_text': facts['description'], 'dates': facts['periods'],
               'source_status': facts['source_status'], 'source_url': facts['official_url'],
               'provider_fields': provider_fields or {}, 'tables': tables}
    record = SimpleNamespace(normalized_payload=payload, body_usable=len(facts['description'].strip()) >= 20,
                             has_source_url=bool(facts['official_url']), attachment_present=False)
    parsed = extract_program_facts(record).to_payload()
    data = info['data']
    for key, reason in (('content_kind', 'program_purpose_unconfirmed'),
                        ('delivery_mode', 'delivery_mode_unknown'), ('activity_region', 'activity_location_unknown')):
        candidate = parsed[key]
        if facts[key] != 'unknown' or key not in detail['editableFields'] or key in operator_fields:
            continue
        if candidate not in {'program', 'offline', 'online', 'hybrid', 'capital', 'not_applicable'}:
            continue
        if key == 'delivery_mode' and data['delivery']['status'] == 'known' and candidate != {
                'onsite': 'offline', 'online': 'online', 'mixed': 'hybrid'}[data['delivery']['value']]:
            result['held'].append('delivery_conflict')
            continue
        if key == 'activity_region' and data['location']['status'] == 'known':
            # Existing typed location owns this relationship; do not infer over it.
            continue
        result['facts_patch'][key] = candidate
        if reason in facts['missing']:
            result['resolve'].append(reason)
    # Extract with current known facts first. New proposals supply unknowns only.
    merged = {**facts, **result['facts_patch']}
    if facts['activity_region'] == 'unknown' and not facts['activity_evidence']:
        merged['activity_evidence'] = parsed['activity_evidence']
    extracted = extract_filter_facts('seoul_reservation', payload, merged)
    for key in ('topic', 'delivery', 'location'):
        old, candidate = data[key], extracted['data'][key]
        if old['status'] != 'unknown' or candidate['status'] != 'known':
            continue
        if info['origins'].get(key) == 'operator':
            result['held'].append('operator:' + key)
            continue
        if key == 'delivery' and merged['delivery_mode'] not in {
                'unknown', {'onsite': 'offline', 'online': 'online', 'mixed': 'hybrid'}[candidate['value']]}:
            continue
        if key == 'location' and merged['activity_region'] not in ('unknown', 'capital'):
            continue
        result['filters_patch'][key] = candidate
        result['evidence'][key] = extracted['evidence'][key]
    projected = {**data, **result['filters_patch']}
    result['remaining_filters'] = missing_filters(projected)
    # Dates, diagnostic flags and operator decisions are never overwritten here.
    return result
