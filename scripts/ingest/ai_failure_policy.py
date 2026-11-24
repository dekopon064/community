"""Explicit one-shot failure handling. No clients, retries or state inference."""
from __future__ import annotations

import re
from dataclasses import dataclass
from ingest.ai_errors import AiJobError, ValidationError
from ingest.ai_worker import AiWorkerResult
from ingest.rpc_errors import RpcAmbiguous, is_timeout_exception, is_lost_response_exception


@dataclass(frozen=True)
class NoRetryResult(AiWorkerResult):
    error_code: str | None = None
    failure_scope: str | None = None
    failure_stage: str | None = None
    diagnostic: dict | None = None
    termination_confirmed: bool = False
    hold_confirmed: bool = False


def terminal_failure_result(error, stage):
    # Continue only for explicit content-validation failures. Unexpected local
    # bugs, provider/auth/budget failures and server contracts stop the batch.
    item = (isinstance(error, AiJobError)
            and error.code in {'ai_schema_error', 'ai_refusal', 'ai_unexpected_thinking'}
            and getattr(error, 'failure_scope', None) != 'batch')
    return NoRetryResult(status='processed', claimed=1, failed=1,
        error_code=error.code if isinstance(error, AiJobError) else 'ai_or_enqueue_failed',
        failure_scope='item' if item else 'batch', failure_stage=stage,
        diagnostic=error.diagnostic if isinstance(error, ValidationError) else None,
        termination_confirmed=True)


def unknown_failure_result(error, stage, *, validation_error=None, validation_stage=None):
    diagnostic = getattr(error, 'diagnostic', None)
    if validation_error is not None:
        diagnostic = {'validation': getattr(validation_error, 'diagnostic', None), 'validationStage': validation_stage,
                      'termination': diagnostic}
    return NoRetryResult(status='ai_state_unknown', claimed=1, state_unknown=1,
        error_code=getattr(validation_error or error, 'code', None),
        failure_scope='batch', failure_stage=stage, diagnostic=diagnostic)


def hold_or_stop(adapter, context, error, stage):
    from ingest.ai_chatgpt_plan import PlanResponseUnknown

    if not isinstance(error, PlanResponseUnknown) or not error.item_scoped:
        return unknown_failure_result(error, stage)
    d = error.diagnostic
    provider_stage = {'review_correction': 'correction'}.get(d['stage'], d['stage'])
    if provider_stage not in ('summary', 'translation', 'correction') or stage not in (provider_stage, 'generation'):
        return unknown_failure_result(error, stage)
    try:
        validate_no_retry_context(context)
        attempt = context['failurePolicy']['attempt']
        evidence = dict(stage=provider_stage, code=d['code'], completedSeen=d['completedSeen'])
        expected = dict(outcome='held', jobId=context['jobId'], revision=context['revision'],
                        attempt=attempt, evidence=evidence)
        receipt = adapter.invoke('hold_program_ai_response', {
            'p_source': context['source'], 'p_job_id': context['jobId'], 'p_revision': context['revision'],
            'p_claimed_at': context['claimedAt'], 'p_lease_until': context['leaseUntil'],
            'p_worker_id': context['workerId'], 'p_attempt': attempt, 'p_evidence': evidence})
        if receipt != expected or type(receipt['evidence']['completedSeen']) is not bool:
            raise RpcAmbiguous()
    except Exception:
        return NoRetryResult(status='ai_state_unknown', claimed=1, state_unknown=1, failure_scope='batch',
                             failure_stage='hold_storage', diagnostic=d)
    return NoRetryResult(status='response_held', claimed=1, failure_scope='item',
                         failure_stage=provider_stage, diagnostic=d, hold_confirmed=True)


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


def terminate_no_retry(adapter, context: dict, error: Exception, *, draft=None, stage=None,
                       failure_rpc='fail_seoul_ai_no_retry', failure_detail=None, draft_source=None) -> None:
    """One fenced write; ambiguous responses are never followed by another write."""
    validate_no_retry_context(context)
    args = {
        'p_job_id': context['jobId'], 'p_revision': context['revision'],
        'p_claimed_at': context['claimedAt'], 'p_lease_until': context['leaseUntil'],
        'p_worker_id': context['workerId'], 'p_attempt': context['failurePolicy']['attempt'],
        'p_error_code': error.code if isinstance(error, AiJobError) else 'ai_or_enqueue_failed',
    }
    if (failure_rpc == 'fail_seoul_ai_no_retry' and draft is None and
            getattr(error, 'diagnostic', {}) == {'rule': 'weekly_schedule_source', 'reason': 'missing_cell_positions'}):
        failure_rpc = 'fail_seoul_ai_weekly_input'
    if draft is not None and draft_source is not None:
        failure_rpc = 'fail_program_ai_with_draft'
        args.update(p_source=draft_source, p_draft=draft)
    elif draft is not None:
        failure_rpc = 'fail_seoul_ai_with_draft'
        args.update(p_draft=draft, p_stage=stage, p_diagnostic=error.diagnostic)
    if failure_detail is not None:
        args["p_failure_detail"] = failure_detail
    status = adapter.invoke(failure_rpc, args)
    if status != 'failed':
        raise RpcAmbiguous()
