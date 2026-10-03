"""My-only validated helpers; keep the deployed Seoul AI implementation unchanged."""
from __future__ import annotations
import re
import unicodedata
from typing import Callable
from uuid import UUID
from ingest.ai_errors import AiJobError
from ingest.ai_worker import AiWorkerResult
from ingest.program_ai import ProgramAIAdapter
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout

def schedule_values(text: str, *, japanese: bool = False) -> dict[str, set]:
    """Small typed check for explicit numeric dates, clock ranges and counts.

    No calendar expansion, AM/PM inference or general Japanese interpretation.
    """
    text = unicodedata.normalize("NFKC", text)
    weekdays = set(re.findall(r"([月火水木金土日])曜日?|[（(]\s*([月火水木金土日])\s*[）)]", text)) if japanese else set(
        re.findall(r"([월화수목금토일])\s*요일|[（(]\s*([월화수목금토일])\s*[）)]", text))
    alphabet = "月火水木金土日" if japanese else "월화수목금토일"
    days = {alphabet.index(a or b) for a, b in weekdays}
    if japanese:
        text = text.translate(str.maketrans({"年": "년", "月": "월", "日": "일", "時": "시", "分": "분", "回": "회"}))
    # A month explicitly governs only its contiguous list of numeric days.
    dates = set()
    for match in re.finditer(r"(\d{1,2})\s*월\s*((?:\d{1,2}\s*일?\s*[,·、・]\s*)*\d{1,2}\s*일)", text):
        dates.update((int(match[1]), int(day)) for day in re.findall(r"\d+", match[2]))
    years = {int(value) for value in re.findall(r"(\d{4})\s*년", text)}
    clock = r"(?:\d{1,2}:[0-5]\d|\d{1,2}\s*시(?:\s*[0-5]?\d\s*분)?)"
    def minutes(value: str) -> int:
        parts = [int(v) for v in re.findall(r"\d+", value)]
        if parts[0] > 23:
            raise AiJobError("ai_schema_error")
        return parts[0] * 60 + (parts[1] if len(parts) > 1 else 0)
    times = {(minutes(m[1]), minutes(m[2])) for m in re.finditer(
        rf"({clock})\s*(?:~|～|〜|–|—|-|부터|から)\s*({clock})", text)}
    counts = {int(v) for v in re.findall(r"(\d+)\s*회", text)}
    return {"dates": dates, "years": years, "weekdays": days, "times": times, "counts": counts}


def section_body(content: str, header: str, headers: tuple[str, ...]) -> str:
    """A real, nonempty section, not a label quoted inside another section."""
    boundary = "|".join(re.escape(h) for h in headers)
    matches = list(re.finditer(r"(?ms)^\s*" + re.escape(header) + r"[ \t]*(.*?)(?=^\s*(?:" + boundary + r")|\Z)", content))
    if len(matches) != 1 or not matches[0][1].strip():
        raise AiJobError("ai_schema_error")
    return matches[0][1].strip()


def process_program_job(adapter: ProgramAIAdapter, *, source_item_id: str, revision: str,
        summarize_ko: Callable, translate_ja: Callable, rpc_source: str, validate: Callable, generate: Callable,
        worker_id: str = "ingest-program-worker", lease_seconds: int = 600) -> AiWorkerResult:
    """Shared explicit-target transport/attempt handling, no general worker claim."""
    if rpc_source not in {"seoul_program", "myseoul_program"}:
        return AiWorkerResult(status="ai_state_unknown")
    try:
        UUID(source_item_id)
        if not re.fullmatch(r"[a-f0-9]{64}", revision) or not 30 <= lease_seconds <= 3600 or not 1 <= len(worker_id.strip()) <= 128:
            raise ValueError()
    except (ValueError, TypeError):
        return AiWorkerResult(status="ai_state_unknown")
    try:
        rows = adapter.invoke(f"claim_{rpc_source}_ai", {"p_source_item_id": source_item_id, "p_revision": revision,
            "p_worker_id": worker_id, "p_lease_seconds": lease_seconds})
        if not isinstance(rows, list) or len(rows) > 1:
            raise RpcAmbiguous()
        if not rows:
            return AiWorkerResult(status="ai_no_jobs")
        c = validate(rows[0], source_item_id, revision, worker_id)
    except Exception:
        # Malformed claim context must not be used to fail/complete some other job.
        return AiWorkerResult(status="ai_state_unknown", state_unknown=1)
    fence = {"p_job_id": c["jobId"], "p_claimed_at": c["claimedAt"], "p_lease_until": c["leaseUntil"], "p_worker_id": worker_id}
    try:
        output = generate(c, summarize_ko=summarize_ko, translate_ja=translate_ja)
        result = adapter.invoke(f"finish_{rpc_source}_ai", {**fence, "p_revision": revision,
            "p_facts_version": c["factsVersion"], "p_output": output})
        if not isinstance(result, dict) or result.get("outcome") not in {"inserted", "duplicate"}:
            raise RpcAmbiguous()
        try:
            UUID(result["candidateId"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise RpcAmbiguous() from None
        return AiWorkerResult(status="processed", claimed=1, completed=1)
    except (RpcAmbiguous, RpcTimeout):
        return AiWorkerResult(status="ai_state_unknown", claimed=1, state_unknown=1)
    except Exception as exc:
        error = exc.code if isinstance(exc, AiJobError) else "ai_or_enqueue_failed"
        try:
            status = adapter.invoke(f"fail_{rpc_source}_ai", {**fence, "p_error_code": error})
            if status not in {"queued", "failed"}:
                raise RpcAmbiguous()
            return AiWorkerResult(status="processed", claimed=1, retried=int(status == "queued"), failed=int(status == "failed"))
        except Exception:
            return AiWorkerResult(status="ai_state_unknown", claimed=1, state_unknown=1)
