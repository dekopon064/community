"""Private failure drafts and an explicit, one-request Seoul correction worker."""
import json
from contextvars import ContextVar
from uuid import UUID

from ingest.ai_errors import AiJobError
from ingest.rpc_errors import RpcAmbiguous

current_output: ContextVar[dict | None] = ContextVar('seoul_failed_output', default=None)


def capture(stage, payload):
    output = current_output.get()
    if output is None or not isinstance(payload, dict):
        return
    fields = {'content_ko': 'ko'} if stage == 'summary' else {'title_ja': 'jaTitle', 'content_ja': 'ja'}
    for source, field in fields.items():
        value = payload.get(source)
        if isinstance(value, str) and 0 < len(value) <= (300 if field == 'jaTitle' else 50_000):
            output[field] = value
    if stage == 'summary' and isinstance(payload.get('facts'), dict):
        facts = payload['facts']
        allowed = {'audience', 'geo_age_income', 'amount_period_deadline', 'how_to_apply'}
        if set(facts) == allowed and all(isinstance(v, str) and len(v) <= 4000 for v in facts.values()):
            output['koFacts'] = facts.copy()


def retained_output(draft):
    if not any(draft.get(k) for k in ('ko', 'ja', 'jaTitle')):
        return None
    # PostgreSQL rejects NUL in jsonb. Never let a malformed/oversize response
    # prevent the ordinary fenced terminal failure.
    encoded = json.dumps(draft, ensure_ascii=False)
    try:
        if r'\u0000' in encoded or len(encoded.encode('utf-8')) > 420_000:
            return None
    except UnicodeEncodeError:
        return None
    return draft


def validated_output(draft, facts, title, classification=None):
    from ingest.ai_claude import validate_summary_payload, validate_translation_payload
    from ingest.ai_worker import (extract_summary_section, KO_SECTION_HEADERS, JA_SECTION_HEADERS,
                                  KO_SUMMARY_HEADER, JA_SUMMARY_HEADER)
    from ingest.seoul_content import assemble_seoul_body, validate_public_body
    from ingest.seoul_public_guidance import validate_public_guidance
    from ingest.region_ja_glossary import validate_japanese_output
    from ingest.translation_validation import validate_translation_fidelity

    ko = validate_summary_payload({'content_ko': draft.get('ko'), 'facts': draft.get('koFacts')})
    summary = extract_summary_section(ko, KO_SUMMARY_HEADER, KO_SECTION_HEADERS)
    if classification is None:
        ko = assemble_seoul_body(ko, facts)
    else:
        from ingest.reclassification_ai import assemble_reclassified_seoul
        ko = assemble_reclassified_seoul(ko, classification)
    if not draft.get('ja') or not draft.get('jaTitle'):
        return None
    title_ja, ja = validate_translation_payload({'title_ja': draft['jaTitle'], 'content_ja': draft['ja']})
    validate_public_body(ja)
    validate_public_guidance(ja, 'ja')
    summary_ja = extract_summary_section(ja, JA_SUMMARY_HEADER, JA_SECTION_HEADERS)
    validate_japanese_output(title_ja, ja, korean_source=title + '\n' + ko)
    validate_translation_fidelity(title, ko, title_ja, ja)
    return dict(titleKo=title, contentKo=ko, summaryKo=summary, titleJa=title_ja,
                contentJa=ja, summaryJa=summary_ja, aiModel=draft['model'])


def process_correction(adapter, draft_id, worker_id, suggest):
    """Consume one operator request. Ambiguous writes are never repeated."""
    UUID(draft_id)
    record = adapter.invoke('claim_seoul_ai_correction', {'p_id': draft_id, 'p_worker': worker_id})
    if not record:
        return 'unavailable'
    if record.get('id') != draft_id or record.get('worker') != worker_id:
        raise RpcAmbiguous()
    field, before, value = (record[key] for key in ('field', 'before', 'value'))
    draft = dict(record['output'])
    original = draft.get(field)
    if not isinstance(original, str) or original.count(before) != 1:
        raise RpcAmbiguous()
    args = {'p_id': draft_id, 'p_worker': worker_id}
    try:
        after = suggest(before=before, evidence=record['evidence'], value=value)
    except AiJobError as exc:
        if exc.code != 'ai_schema_error' or getattr(exc, 'failure_scope', None) == 'batch':
            raise
        after = None
    if (not isinstance(after, str) or not 1 <= len(after) <= 500 or '\n' in after or '\r' in after
            or before == after or value not in after or after.strip() != after):
        return adapter.invoke('complete_seoul_ai_correction', {**args, 'p_after': None, 'p_candidate': None,
                              'p_result': 'invalid_suggestion'})
    draft[field] = original.replace(before, after, 1)
    try:
        candidate = validated_output(draft, record['facts'], record['title'], record.get('classification'))
    except AiJobError:
        candidate = None
        result = 'validation_failed'
    else:
        result = 'validated' if candidate else 'translation_missing'
    return adapter.invoke('complete_seoul_ai_correction', {**args, 'p_after': after, 'p_candidate': candidate,
                          'p_result': result})


