"""Secret-safe AI job errors. Do not attach response bodies or keys."""

from __future__ import annotations

AI_OR_ENQUEUE_FAILED = "ai_or_enqueue_failed"
AI_UNEXPECTED_THINKING = "ai_unexpected_thinking"
MAX_ERROR_CODE_LENGTH = 64

ALLOWED_AI_ERROR_CODES = frozenset(
    {
        AI_OR_ENQUEUE_FAILED,
        "ai_blocked_cost_cap",
        "ai_cost_bound_breach",
        "ai_refusal",
        "ai_schema_error",
        "ai_timeout",
        "ai_network",
        "ai_http_400",
        "ai_http_401",
        "ai_http_403",
        "ai_http_404",
        "ai_http_429",
        "ai_http_4xx",
        "ai_http_5xx",
        AI_UNEXPECTED_THINKING,
        "ai_call_budget",
        "ai_sampling_forbidden",
    }
)


class AiJobError(Exception):
    """Deterministic AI failure with a Secret-safe code for fail_processing_job."""

    def __init__(self, code: str) -> None:
        safe = code if code in ALLOWED_AI_ERROR_CODES else AI_OR_ENQUEUE_FAILED
        if len(safe) > MAX_ERROR_CODE_LENGTH:
            safe = AI_OR_ENQUEUE_FAILED
        self.code = safe
        super().__init__(safe)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code!r})"
