"""Claude Sonnet 5 ingest adapter. Structured JSON only. No sampling. No SDK retry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ingest.ai_errors import AI_UNEXPECTED_THINKING, AiJobError

SONNET_MODEL = "claude-sonnet-5"
SUMMARY_MAX_TOKENS = 2048
TRANSLATION_MAX_TOKENS = 4096
CLAUDE_JOB_USD_CAP = 0.10
INPUT_PAD_FACTOR = 1.1
SONNET_INPUT_USD_PER_MTOK = 2.0
SONNET_OUTPUT_USD_PER_MTOK = 10.0
COUNT_TIMEOUT_S = 30.0
INFERENCE_TIMEOUT_S = 120.0
MAX_COUNT_CALLS = 2
MAX_CREATE_CALLS = 2
CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS = 2048
BANNED_SAMPLING_KEYS = frozenset({"temperature", "top_p", "top_k"})
BANNED_EXTRA_KEYS = frozenset({"extra_body", "extra_headers", "extra_query", "betas"})
UNEXPECTED_THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})
_PACKAGE_DIR = Path(__file__).resolve().parent


def _load_text(relative: str) -> str:
    return (_PACKAGE_DIR / relative).read_text(encoding="utf-8")


def _load_json(relative: str) -> dict[str, Any]:
    return json.loads(_load_text(relative))


SUMMARY_SYSTEM = _load_text("claude_prompts/summary_system.txt")
TRANSLATION_SYSTEM = _load_text("claude_prompts/translation_system.txt")
SUMMARY_SCHEMA = _load_json("claude_schemas/summary.schema.json")
TRANSLATION_SCHEMA = _load_json("claude_schemas/translation.schema.json")


def translation_prompt_schema_overhead_tokens() -> int:
    encoded = json.dumps(TRANSLATION_SCHEMA, ensure_ascii=False, separators=(",", ":"))
    return len(TRANSLATION_SYSTEM) + len(encoded)


def conservative_cost_usd(input_tokens: int, output_tokens: int) -> float:
    padded_input = int(input_tokens * INPUT_PAD_FACTOR)
    return (
        padded_input * SONNET_INPUT_USD_PER_MTOK
        + output_tokens * SONNET_OUTPUT_USD_PER_MTOK
    ) / 1_000_000


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AiJobError("ai_schema_error")
    return value


def validate_summary_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AiJobError("ai_schema_error")
    extra = set(payload) - {"content_ko", "facts"}
    if extra:
        raise AiJobError("ai_schema_error")
    content_ko = _require_string(payload.get("content_ko"), "content_ko")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise AiJobError("ai_schema_error")
    required_facts = {
        "audience",
        "geo_age_income",
        "amount_period_deadline",
        "how_to_apply",
    }
    if set(facts) != required_facts:
        raise AiJobError("ai_schema_error")
    for key in required_facts:
        if not isinstance(facts[key], str):
            raise AiJobError("ai_schema_error")
    return content_ko


def validate_translation_payload(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise AiJobError("ai_schema_error")
    extra = set(payload) - {"title_ja", "content_ja"}
    if extra:
        raise AiJobError("ai_schema_error")
    title_ja = _require_string(payload.get("title_ja"), "title_ja")
    content_ja = _require_string(payload.get("content_ja"), "content_ja")
    return title_ja, content_ja


def _thinking_disabled() -> dict[str, str]:
    return {"type": "disabled"}


def _output_config(schema: dict[str, Any]) -> dict[str, Any]:
    return {"format": {"type": "json_schema", "schema": schema}}


def build_summary_create_kwargs(*, title: str, body: str, source_url: str | None) -> dict[str, Any]:
    user = (
        f"title: {title}\n"
        f"source_url: {source_url or ''}\n"
        f"body:\n{body}"
    )
    return {
        "model": SONNET_MODEL,
        "max_tokens": SUMMARY_MAX_TOKENS,
        "system": SUMMARY_SYSTEM,
        "messages": [{"role": "user", "content": user}],
        "thinking": _thinking_disabled(),
        "output_config": _output_config(SUMMARY_SCHEMA),
        "timeout": INFERENCE_TIMEOUT_S,
    }


def build_translation_create_kwargs(*, title_ko: str, content_ko: str) -> dict[str, Any]:
    user = f"title_ko: {title_ko}\ncontent_ko:\n{content_ko}"
    return {
        "model": SONNET_MODEL,
        "max_tokens": TRANSLATION_MAX_TOKENS,
        "system": TRANSLATION_SYSTEM,
        "messages": [{"role": "user", "content": user}],
        "thinking": _thinking_disabled(),
        "output_config": _output_config(TRANSLATION_SCHEMA),
        "timeout": INFERENCE_TIMEOUT_S,
    }


def count_kwargs_from_create(params: dict[str, Any]) -> dict[str, Any]:
    counted = dict(params)
    counted.pop("max_tokens", None)
    counted["timeout"] = COUNT_TIMEOUT_S
    return counted


def assert_request_contract(params: dict[str, Any], *, stage: str) -> None:
    banned = (BANNED_SAMPLING_KEYS | BANNED_EXTRA_KEYS) & set(params)
    if banned:
        raise AiJobError("ai_sampling_forbidden")
    if params.get("model") != SONNET_MODEL:
        raise AiJobError("ai_schema_error")
    thinking = params.get("thinking")
    if thinking != {"type": "disabled"}:
        raise AiJobError("ai_schema_error")
    output_config = params.get("output_config")
    if not isinstance(output_config, dict):
        raise AiJobError("ai_schema_error")
    fmt = output_config.get("format")
    if not isinstance(fmt, dict) or fmt.get("type") != "json_schema":
        raise AiJobError("ai_schema_error")
    schema = fmt.get("schema")
    expected = SUMMARY_SCHEMA if stage == "summary" else TRANSLATION_SCHEMA
    if schema != expected:
        raise AiJobError("ai_schema_error")


def _usage_int(usage: Any, name: str) -> int:
    value = getattr(usage, name, None)
    if value is None and isinstance(usage, dict):
        value = usage.get(name)
    if not isinstance(value, int) or value < 0:
        return 0
    return value


def _thinking_tokens(usage: Any) -> int:
    details = getattr(usage, "output_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("output_tokens_details")
    if details is None:
        return 0
    value = getattr(details, "thinking_tokens", None)
    if value is None and isinstance(details, dict):
        value = details.get("thinking_tokens")
    if isinstance(value, int) and value > 0:
        return value
    return 0


def map_anthropic_exception(exc: BaseException) -> AiJobError:
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if name in {"APITimeoutError", "TimeoutException", "ReadTimeout", "TimeoutError"}:
        return AiJobError("ai_timeout")
    if name in {"APIConnectionError", "APIConnectionTimeoutError"}:
        return AiJobError("ai_network")
    if status == 429 or name == "RateLimitError":
        return AiJobError("ai_http_429")
    if status == 401 or name == "AuthenticationError":
        return AiJobError("ai_http_401")
    if status == 400 or name == "BadRequestError":
        return AiJobError("ai_http_400")
    if status == 403 or name == "PermissionDeniedError":
        return AiJobError("ai_http_403")
    if status == 404 or name == "NotFoundError":
        return AiJobError("ai_http_404")
    if isinstance(status, int) and status >= 500:
        return AiJobError("ai_http_5xx")
    if isinstance(status, int) and 400 <= status < 500:
        return AiJobError("ai_http_4xx")
    return AiJobError("ai_network")


def _extract_text(message: Any) -> str:
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        raise AiJobError("ai_refusal")
    content = getattr(message, "content", None)
    if not isinstance(content, list) or not content:
        raise AiJobError("ai_schema_error")
    texts: list[str] = []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type is None and isinstance(block, dict):
            block_type = block.get("type")
        if block_type in UNEXPECTED_THINKING_BLOCK_TYPES:
            raise AiJobError(AI_UNEXPECTED_THINKING)
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if isinstance(text, str):
            texts.append(text)
    if not texts:
        raise AiJobError("ai_schema_error")
    return "".join(texts)


def _parse_json_object(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AiJobError("ai_schema_error") from exc


def _input_tokens_from_count(result: Any) -> int:
    value = getattr(result, "input_tokens", None)
    if value is None and isinstance(result, dict):
        value = result.get("input_tokens")
    if not isinstance(value, int) or value < 0:
        raise AiJobError("ai_schema_error")
    return value


class ClaudeAdapter:
    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        if client is None:
            from anthropic import Anthropic

            if not api_key:
                raise AiJobError("ai_or_enqueue_failed")
            client = Anthropic(api_key=api_key, max_retries=0)
        max_retries = getattr(client, "max_retries", None)
        if max_retries != 0:
            raise AiJobError("ai_or_enqueue_failed")
        self._client = client
        self._reset_job()

    def _reset_job(self) -> None:
        self._count_calls = 0
        self._create_calls = 0
        self._summary_input_tokens: int | None = None
        self._translation_input_bound: int | None = None
        self._spent_actual_usd = 0.0

    def summarize_ko(
        self,
        body: str,
        source_url: str | None,
        title: str | None = None,
    ) -> tuple[str, str, str]:
        self._reset_job()
        create_kwargs = build_summary_create_kwargs(
            title=title or "",
            body=body,
            source_url=source_url,
        )
        assert_request_contract(create_kwargs, stage="summary")
        summary_input = self._count_tokens(create_kwargs)
        self._summary_input_tokens = summary_input
        translation_bound = (
            summary_input + SUMMARY_MAX_TOKENS + CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS
        )
        self._translation_input_bound = translation_bound
        pre_max = conservative_cost_usd(summary_input, SUMMARY_MAX_TOKENS) + conservative_cost_usd(
            translation_bound,
            TRANSLATION_MAX_TOKENS,
        )
        if pre_max > CLAUDE_JOB_USD_CAP:
            raise AiJobError("ai_blocked_cost_cap")
        message = self._create(create_kwargs)
        self._record_actual(message)
        payload = _parse_json_object(_extract_text(message))
        content_ko = validate_summary_payload(payload)
        return content_ko, "success", SONNET_MODEL

    def translate_ja(
        self,
        title: str,
        content_ko: str,
    ) -> tuple[str, str, str, str]:
        if self._summary_input_tokens is None or self._translation_input_bound is None:
            raise AiJobError("ai_or_enqueue_failed")
        create_kwargs = build_translation_create_kwargs(
            title_ko=title,
            content_ko=content_ko,
        )
        assert_request_contract(create_kwargs, stage="translation")
        actual_translation_input = self._count_tokens(create_kwargs)
        if actual_translation_input > self._translation_input_bound:
            raise AiJobError("ai_cost_bound_breach")
        remaining = conservative_cost_usd(actual_translation_input, TRANSLATION_MAX_TOKENS)
        if self._spent_actual_usd + remaining > CLAUDE_JOB_USD_CAP:
            raise AiJobError("ai_blocked_cost_cap")
        message = self._create(create_kwargs)
        self._record_actual(message)
        payload = _parse_json_object(_extract_text(message))
        title_ja, content_ja = validate_translation_payload(payload)
        return title_ja, content_ja, "success", SONNET_MODEL

    def _count_tokens(self, create_kwargs: dict[str, Any]) -> int:
        if self._count_calls >= MAX_COUNT_CALLS:
            raise AiJobError("ai_call_budget")
        self._count_calls += 1
        params = count_kwargs_from_create(create_kwargs)
        try:
            result = self._client.messages.count_tokens(**params)
        except AiJobError:
            raise
        except Exception as exc:  # noqa: BLE001 - map SDK exceptions
            raise map_anthropic_exception(exc) from None
        return _input_tokens_from_count(result)

    def _create(self, create_kwargs: dict[str, Any]) -> Any:
        if self._create_calls >= MAX_CREATE_CALLS:
            raise AiJobError("ai_call_budget")
        self._create_calls += 1
        try:
            return self._client.messages.create(**create_kwargs)
        except AiJobError:
            raise
        except Exception as exc:  # noqa: BLE001 - map SDK exceptions
            raise map_anthropic_exception(exc) from None

    def _record_actual(self, message: Any) -> None:
        usage = getattr(message, "usage", None)
        if _thinking_tokens(usage) > 0:
            raise AiJobError(AI_UNEXPECTED_THINKING)
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        self._spent_actual_usd += (
            input_tokens * SONNET_INPUT_USD_PER_MTOK
            + output_tokens * SONNET_OUTPUT_USD_PER_MTOK
        ) / 1_000_000
