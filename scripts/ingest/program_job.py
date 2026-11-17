"""Reusable, fenced worker transport for registered program sources."""
from __future__ import annotations
import re
from typing import Callable
from uuid import UUID
from ingest.ai_errors import AiJobError
from ingest.ai_failure_policy import (terminal_failure_result, terminate_no_retry, uncertain_failure,
                                     unknown_failure_result, validate_no_retry_context)
from ingest.program_candidate_review import ProgramCandidateReview, private_output, validate_candidate_fields
from ingest.seoul_ai_correction import current_output
from ingest.program_failure_diagnostic import program_failure_detail
from ingest.content_filters import validate_claim_filter, validate_program_filter_snapshot
from ingest.ai_worker import AiWorkerResult
from ingest.program_ai import ProgramAIAdapter
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout

# Only trusted adapters can opt a source into terminal writes. Never derive a
# failure endpoint from queue data or fall back to the retrying RPC.
PROGRAM_FAILURE_ENDPOINTS = {
    "seoul_program": "fail_seoul_ai_no_retry",
    "myseoul_program": "fail_myseoul_ai_no_retry",
}

def process_program_job(adapter: ProgramAIAdapter, *, source_item_id: str, revision: str,
        summarize_ko: Callable, translate_ja: Callable, rpc_source: str, validate: Callable, generate: Callable, review_source: Callable,
        worker_id: str = "ingest-program-worker", lease_seconds: int = 600,
        no_retry: bool = False) -> AiWorkerResult:
    """Shared explicit-target transport/attempt handling, no general worker claim."""
    if rpc_source not in PROGRAM_FAILURE_ENDPOINTS or type(no_retry) is not bool:
        return AiWorkerResult(status="ai_state_unknown")
    try:
        UUID(source_item_id)
        if not re.fullmatch(r"[a-f0-9]{64}", revision) or not 30 <= lease_seconds <= 3600 or not 1 <= len(worker_id.strip()) <= 128:
            raise ValueError()
    except (ValueError, TypeError):
        return AiWorkerResult(status="ai_state_unknown")
    try:
        claim_rpc = f"claim_{rpc_source}_ai" + ("_no_retry" if no_retry else "")
        rows = adapter.invoke(claim_rpc, {"p_source_item_id": source_item_id, "p_revision": revision,
            "p_worker_id": worker_id, "p_lease_seconds": lease_seconds})
        if not isinstance(rows, list) or len(rows) > 1:
            raise RpcAmbiguous()
        if not rows:
            return AiWorkerResult(status="ai_no_jobs")
        c = validate(rows[0], source_item_id, revision, worker_id)
        if no_retry:
            validate_no_retry_context(c)
        if c.get("filterContext") is not None:
            validate_claim_filter(c["filterContext"], worker=worker_id, fence=c,
                                  category=c.get("publicCategory", "program"))
            validate_program_filter_snapshot(c["filterContext"]["data"], c["facts"])
    except Exception as exc:
        if no_retry:
            return unknown_failure_result(exc, "claim")
        # Malformed claim context must not be used to fail/complete some other job.
        return AiWorkerResult(status="ai_state_unknown", state_unknown=1)
    fence = {"p_job_id": c["jobId"], "p_claimed_at": c["claimedAt"], "p_lease_until": c["leaseUntil"], "p_worker_id": worker_id}
    draft = {}
    token = current_output.set(draft if no_retry else None)
    owner = getattr(translate_ja, '__self__', None)
    review = ProgramCandidateReview(getattr(owner, 'suggest_program_review', None)) if no_retry else None
    stage = "generation"
    try:
        output = generate(c, summarize_ko=summarize_ko, translate_ja=translate_ja, review=review)
        if no_retry:
            stage = "japanese_validation"
            validate_candidate_fields(output)
        metadata = None
        if review and review.issues:
            stage = "correction"
            metadata = review.propose(output, review_source(c))
        stage = "candidate_completion"
        args = {**fence, "p_revision": revision, "p_facts_version": c["factsVersion"], "p_output": output}
        if metadata is None:
            result = adapter.invoke(f"finish_{rpc_source}_ai", args)
        else:
            result = adapter.invoke("finish_program_ai_candidate_review", {**args, "p_source": c["source"], "p_review": metadata})
        if not isinstance(result, dict) or result.get("outcome") not in {"inserted", "duplicate"}:
            raise RpcAmbiguous()
        try:
            UUID(result["candidateId"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise RpcAmbiguous() from None
        return AiWorkerResult(status="processed", claimed=1, completed=1)
    except Exception as exc:
        stage = getattr(exc, "failure_stage", stage)
        if no_retry:
            if stage == "candidate_completion" or uncertain_failure(exc):
                return unknown_failure_result(exc, stage)
            try:
                terminate_no_retry(adapter, c, exc, failure_rpc=PROGRAM_FAILURE_ENDPOINTS[rpc_source],
                                   failure_detail=program_failure_detail(stage, exc),
                                   draft=private_output(draft), draft_source=c["source"])
            except Exception as finish_error:
                return unknown_failure_result(finish_error, "failure_termination", validation_error=exc, validation_stage=stage)
            return terminal_failure_result(exc, stage)
        if isinstance(exc, (RpcAmbiguous, RpcTimeout)):
            return AiWorkerResult(status="ai_state_unknown", claimed=1, state_unknown=1)
        error = exc.code if isinstance(exc, AiJobError) else "ai_or_enqueue_failed"
        try:
            status = adapter.invoke(f"fail_{rpc_source}_ai", {**fence, "p_error_code": error})
            if status not in {"queued", "failed"}:
                raise RpcAmbiguous()
            return AiWorkerResult(status="processed", claimed=1, retried=int(status == "queued"), failed=int(status == "failed"))
        except Exception:
            return AiWorkerResult(status="ai_state_unknown", claimed=1, state_unknown=1)
    finally:
        current_output.reset(token)
