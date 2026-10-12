"""Pure operator-approved publication cohort plan. No DB, AI, policy or backfill."""
from __future__ import annotations
import copy
import re
from datetime import datetime, timedelta, timezone, date
from uuid import UUID
from ingest.content_filters import validate_filters, field
from ingest.source_identity import canonical_source_id

KST = timezone(timedelta(hours=9))

def publication_plan(items: list[dict], *, first_day: str, last_day: str) -> dict:
    """Dates select a human-confirmed cohort; they never infer nationality.

    publishedAt must be the service's publication timestamp, not a source date.
    Plans carry existing fences and never apply a patch or increment a version.
    """
    if type(items) is not list or len(items) > 1000:
        raise ValueError('invalid_publication_snapshot')
    start = datetime.combine(date.fromisoformat(first_day), datetime.min.time(), KST)
    end = datetime.combine(date.fromisoformat(last_day) + timedelta(days=1), datetime.min.time(), KST)
    if start >= end:
        raise ValueError('invalid_publication_range')
    result = {'updates': [], 'already_classified': [], 'conflicts': [], 'skipped': [], 'unverified': []}
    seen = set()
    for raw in items:
        item = copy.deepcopy(raw)
        try:
            identity = str(UUID(item['id']))
            if identity in seen:
                raise ValueError('duplicate_publication')
            seen.add(identity)
            source = canonical_source_id(item['source'])
            timestamp = datetime.fromisoformat(item['publishedAt'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('publication_timezone_missing')
        except (ValueError, TypeError, KeyError, AttributeError):
            result['unverified'].append({'id': item.get('id'), 'reason': 'publication_identity_or_time_unverified'})
            continue
        if source != 'myseoul_program' or not start <= timestamp < end:
            result['skipped'].append({'id': identity, 'reason': 'outside_operator_confirmed_cohort'})
            continue
        try:
            source_id = str(UUID(item['sourceItemId']))
            if any(not isinstance(item.get(k), str) or not re.fullmatch('[a-f0-9]{64}', item[k]) for k in ('revision','version')):
                raise ValueError('missing_fence')
            if type(item.get('filterVersion')) is not int or not 1 <= item['filterVersion'] <= 9007199254740991:
                raise ValueError('missing_filter_version')
            data = validate_filters(item['contentFilters'])
            if data['category'] != 'program' or item.get('category') != 'program':
                raise ValueError('category_conflict')
        except (ValueError, TypeError, KeyError):
            result['unverified'].append({'id': identity, 'reason': 'saved_filters_or_fences_unverified'})
            continue
        classification = data['foreignerProgram']
        if classification == field('foreigner'):
            result['already_classified'].append({'id': identity, 'reason': 'already_operator_target_value'})
        elif classification['status'] == 'known':
            result['conflicts'].append({'id': identity, 'before': classification, 'proposed': field('foreigner')})
        else:
            result['updates'].append({'id': identity, 'sourceItemId': source_id, 'title': item.get('title'),
                'publishedAt': item['publishedAt'], 'revision': item['revision'], 'version': item['version'],
                'filterVersion': item['filterVersion'], 'before': classification,
                'patch': {'foreignerProgram': field('foreigner')}, 'basis': 'operator_confirmed_cohort'})
    return result
