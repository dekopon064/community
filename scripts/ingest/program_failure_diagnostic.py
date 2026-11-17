"""Bounded operator diagnostics; never transport model text or provider exceptions."""
import json
from pathlib import Path
from uuid import UUID

from ingest.ai_errors import ALLOWED_AI_ERROR_CODES, AiJobError, ValidationError, _diagnostic_location, _FACT_LABELS

LABELS = json.loads((Path(__file__).resolve().parents[2] / 'app/lib/pc-worker/failure-labels.json').read_text(encoding='utf-8'))


def comparison(value, depth=0):
    if value is None or type(value) is bool:
        return value
    if type(value) is int and abs(value) <= 1_000_000_000:
        return value
    if isinstance(value, str) and value in _FACT_LABELS:
        return value
    if isinstance(value, str) and len(value) <= 18:
        import re
        if re.fullmatch(r'-?[0-9]{1,10}(?:\.[0-9]{1,6})?', value):
            return value
    if isinstance(value, list) and depth < 3:
        return [comparison(part, depth + 1) for part in value[:6]]
    return None


def safe_detail(stage, code, diagnostic):
    d = diagnostic if isinstance(diagnostic, dict) else {}
    location = d.get('location')
    result = {'stage': stage if stage in LABELS['stage'] else 'unknown',
              'code': code if code in ALLOWED_AI_ERROR_CODES else 'unknown',
              'rule': d.get('rule') if d.get('rule') in LABELS['rule'] else 'unknown',
              'reason': d.get('reason') if d.get('reason') in LABELS['reason'] else 'unknown'}
    if isinstance(location, dict):
        result['location'] = _diagnostic_location(location)
    if result['rule'] != 'unknown':
        for key in ('expected', 'actual'):
            if key in d:
                result[key] = comparison(d[key])
    return result


def program_failure_detail(stage, error):
    return safe_detail(stage, error.code if isinstance(error, AiJobError) else 'ai_or_enqueue_failed',
                       error.diagnostic if isinstance(error, ValidationError) else None)


def batch_failures(items, stopped):
    """The next row records actual processing, including across chunk boundaries."""
    rows = []
    for index, item in enumerate(items):
        if not (item['failed'] or item['retried'] or item['stateUnknown']):
            continue
        stage, diagnostic = item['failureStage'], item['diagnostic']
        if stage == 'failure_termination' and isinstance(diagnostic, dict):
            original = diagnostic.get('validationStage')
            diagnostic = diagnostic.get('validation')
        else:
            original = None
        detail = safe_detail(original or stage, item['errorCode'], diagnostic)
        rows.append(dict(source=item['sourceName'], sourceItemId=str(UUID(item['sourceItemId'])),
                         sequence=index+1, detail=detail,
                         stopStage=stage if stage in LABELS['stage'] and stopped and index+1 == len(items) else None,
                         terminationConfirmed=item['terminationConfirmed'],
                         flow='continued' if index+1 < len(items) else 'stopped' if stopped else 'last'))
    return rows
