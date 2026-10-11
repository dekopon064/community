"""Fixed diagnostic codes only: no credentials, URLs, response text or SQL."""
from ingest.connectors.seoul_reservation import SeoulContractError
from ingest.http_client import HttpBudgetExhausted, HttpRequestFailed, HttpStatusError, ResponseTooLarge
from ingest.rpc_errors import RpcAmbiguous, RpcError

SEOUL_CODES = frozenset({
    'seoul_item_invalid', 'seoul_field_type_invalid', 'seoul_id_invalid', 'seoul_title_missing',
    'seoul_body_too_large', 'seoul_link_invalid', 'seoul_limits_invalid',
    'seoul_checkpoint_out_of_range', 'seoul_api_key_missing_or_invalid',
    'seoul_credential_in_response', 'seoul_response_invalid', 'seoul_api_result_error',
    'seoul_page_shape_invalid', 'seoul_duplicate_id_in_page', 'seoul_repeated_page',
    'seoul_revision_changed_during_scan', 'seoul_overlapping_pages',
})
HTTP_CODES = frozenset({'timeout', 'request_failed', 'non_json', 'invalid_json', 'invalid_utf8',
                        'http_status_error', 'http_budget_exhausted', 'response_too_large'})
STAGES = frozenset({'checkpoint', 'configuration', 'api_read', 'response_contract', 'page_contract',
                    'row_normalization', 'row_identity', 'page_identity', 'read_complete', 'http_request',
                    'http_status', 'body_read', 'json_decode', 'http_complete', 'planning',
                    'new_only_store', 'finish_run'})
NUMBERS = ('page', 'attempt', 'http_status', 'response_bytes', 'declared_bytes',
           'json_error_position', 'row_count', 'total_count', 'row_index')

def failure_diagnostic(connector, exc, *, stage=None):
    source = getattr(connector, 'last_diagnostic', {})
    http = getattr(getattr(connector, 'http', None), 'last_diagnostic', {})
    source = source if type(source) is dict else {}
    http = http if type(http) is dict else {}
    current = stage or source.get('stage')
    if current == 'api_read':
        current = http.get('stage', current)
    result = {'stage': current if isinstance(current, str) and current in STAGES else 'unknown', 'error_code': 'unexpected_error'}
    if isinstance(exc, SeoulContractError) and exc.args and isinstance(exc.args[0], str) and exc.args[0] in SEOUL_CODES:
        result['error_code'] = exc.args[0]
    elif isinstance(exc, HttpBudgetExhausted): result['error_code'] = 'http_budget_exhausted'
    elif isinstance(exc, ResponseTooLarge): result['error_code'] = 'response_too_large'
    elif isinstance(exc, HttpStatusError): result['error_code'] = 'http_status_error'
    elif isinstance(exc, HttpRequestFailed):
        code = http.get('error_code', exc.kind)
        result['error_code'] = code if isinstance(code, str) and code in HTTP_CODES else 'request_failed'
    elif isinstance(exc, RpcAmbiguous): result['error_code'] = 'rpc_ambiguous'
    elif isinstance(exc, RpcError): result['error_code'] = 'rpc_failure'
    for key in NUMBERS:
        value = source.get(key, http.get(key))
        if type(value) is int and value >= 0:
            result[key] = value
    code = source.get('api_code')
    import re
    if isinstance(code, str) and re.fullmatch(r'(?:INFO|ERROR)-[0-9]{3}', code):
        result['api_code'] = code
    return result

def diagnose_read(connector):
    """One bounded read; no store, lease, RPC or AI call."""
    if connector.page_size != 50 or connector.max_pages != 1 or connector.http.budget != 1 or connector.http.max_attempts != 1:
        raise ValueError('one_read_diagnostic_limits_required')
    try:
        page = connector.fetch_batch(None)
        from ingest.seoul_workflow import plan_collection
        plan = plan_collection(list(page.items),existing_keys=frozenset(),natural_end=page.natural_end)
        return dict(mode='diagnostic_read_only', status='read_complete', scanned=len(page.items),
                    culture_count=plan.counters['target'], other_category=plan.counters['other_category'],
                    valid_target_count=plan.counters['new_planned'], rejected_count=plan.counters['failed'],
                    validation='incomplete' if plan.counters['failed'] else 'valid',item_errors=plan.counters['item_errors'],
                    coverage='listing_natural_end' if page.natural_end else 'bounded_page_only',
                    request_count=connector.http.request_count, writes=0, ai_calls=0)
    except Exception as exc:
        return dict(mode='diagnostic_read_only', status='failed', diagnostic=failure_diagnostic(connector, exc),
                    request_count=connector.http.request_count, writes=0, ai_calls=0)
