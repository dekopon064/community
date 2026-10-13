"""Explicit one-shot failure handling. No clients, retries or state inference."""
from __future__ import annotations

import re
from ingest.ai_errors import AiJobError
from ingest.rpc_errors import RpcAmbiguous, is_timeout_exception, is_lost_response_exception


def validate_no_retry_context(context: dict) -> None:
    policy = context.get('failurePolicy')
    if (type(policy) is not dict or set(policy) != {'policy', 'attempt'}
            or policy['policy'] != 'no_retry' or type(policy['attempt']) is not str
            or not re.fullmatch('[a-f0-9]{64}', policy['attempt'])):
        raise RpcAmbiguous()


def uncertain_failure(exc: Exception) -> bool:
    return (isinstance(exc, RpcAmbiguous) or is_timeout_exception(exc)
            or is_lost_response_exception(exc)
            or isinstance(exc, AiJobError) and exc.code in {'ai_timeout', 'ai_network'})


def terminate_no_retry(adapter, context: dict, error: Exception) -> None:
    """One fenced write; ambiguous responses are never followed by another write."""
    validate_no_retry_context(context)
    status = adapter.invoke('fail_seoul_ai_no_retry', {
        'p_job_id': context['jobId'], 'p_revision': context['revision'],
        'p_claimed_at': context['claimedAt'], 'p_lease_until': context['leaseUntil'],
        'p_worker_id': context['workerId'], 'p_attempt': context['failurePolicy']['attempt'],
        'p_error_code': error.code if isinstance(error, AiJobError) else 'ai_or_enqueue_failed',
    })
    if status != 'failed':
        raise RpcAmbiguous()
