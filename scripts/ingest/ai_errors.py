"""Secret-safe AI job errors. Do not attach response bodies or keys."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from itertools import islice

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

# Comparison values come from parsers, never from raw model or source text.
_FACT_LABELS = frozenset({
    'date', 'time', 'people', 'families', 'age', 'count', 'minimum',
    'maximum', 'under', 'over', 'approximately',
})


def _diagnostic_value(value, depth=0):
    if value is None or type(value) is bool:
        return value
    if type(value) is int and abs(value) <= 1_000_000_000:
        return value
    if type(value) is Decimal and value.is_finite() and abs(value) <= 1_000_000_000:
        return format(round(value, 6), 'f').rstrip('0').rstrip('.') if value else '0'
    if type(value) is str and value in _FACT_LABELS:
        return value
    if type(value) in (tuple, list) and depth < 3:
        return [_diagnostic_value(part, depth + 1) for part in islice(value, 6)]
    return None


_LOCATION_LABELS = {
    'field': frozenset({
        'content_ko', 'title_ja', 'content_ja', 'title', 'body', 'facts',
        'facts.audience', 'facts.geo_age_income', 'facts.amount_period_deadline',
        'facts.how_to_apply', 'one_line_summary',
    }),
    'period_role': frozenset({'application', 'operation', 'meeting', 'deadline'}),
}


def _diagnostic_location(location):
    return {key: value for key, value in location.items()
            if (key in {'table', 'row', 'column', 'line', 'item'} and type(value) is int and 0 <= value <= 100_000)
            or (key in _LOCATION_LABELS and type(value) is str and value in _LOCATION_LABELS[key])}


class ValidationError(AiJobError):
    """Keep the persisted code and attach bounded, structured local diagnostics."""

    def __init__(self, rule, reason, *, location=None, expected=None, actual=None):
        super().__init__('ai_schema_error')
        self.diagnostic = {'rule': rule, 'reason': reason}
        if location and (position := _diagnostic_location(location)):
            self.diagnostic['location'] = position
        if expected is not None or actual is not None:
            self.diagnostic.update(expected=_diagnostic_value(expected), actual=_diagnostic_value(actual))


@contextmanager
def validation_location(**location):
    """Add fixed labels and 1-based coordinates as a validation error propagates."""
    try:
        yield
    except ValidationError as error:
        position = _diagnostic_location(location)
        if position:
            error.diagnostic['location'] = {**position, **error.diagnostic.get('location', {})}
        raise
