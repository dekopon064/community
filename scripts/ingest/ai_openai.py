"""GPT-6.1 Sol Responses adapter. Explicit provider; two generations, no retry.

Uses the deployed prompts/schemas and validation unchanged. Reasoning is included
in the existing output ceilings and job cap, never granted an extra budget.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from ingest.ai_errors import AiJobError
from ingest.ai_claude import (SUMMARY_SYSTEM, MYSEOUL_SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM, summary_system_prompt,
    SUMMARY_SCHEMA, TRANSLATION_SCHEMA, SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS,
    COUNT_TIMEOUT_S, INFERENCE_TIMEOUT_S, CLAUDE_JOB_USD_CAP,
    CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS, validate_summary_payload,
    validate_translation_payload, translation_system_prompt)
from ingest.region_ja_glossary import validate_japanese_output
from ingest.translation_validation import validate_translation_fidelity

GPT_MODEL = 'gpt-6.1-sol'
GPT_REASONING_EFFORT = 'low'
GPT_JOB_USD_CAP = CLAUDE_JOB_USD_CAP
MAX_CREATE_CALLS = 2
MAX_COUNT_CALLS = 2
OUTPUT_USD_PER_MTOK = 10.0
CACHE_WRITE_USD_PER_MTOK = 2.5


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise AiJobError('ai_schema_error')
    return value


def bounded_cost(input_tokens: int, output_tokens: int) -> float:
    # Includes possible cache writes at the higher input rate; no cache discount
    # is needed to fit the cap. These short requests never enter long-context tiers.
    return (int(input_tokens * 1.1) * CACHE_WRITE_USD_PER_MTOK
            + output_tokens * OUTPUT_USD_PER_MTOK) / 1_000_000


def build_request(*, instructions: str, user: str, stage: str) -> dict:
    if stage not in {'summary', 'translation'}:
        raise AiJobError('ai_schema_error')
    schema = copy.deepcopy(SUMMARY_SCHEMA if stage == 'summary' else TRANSLATION_SCHEMA)
    # JSON-schema annotations are transport metadata, not candidate fields.
    schema.pop('$schema', None)
    schema.pop('$id', None)
    return {'model': GPT_MODEL, 'instructions': instructions,
        'input': [{'role': 'user', 'content': user}],
        'text': {'format': {'type': 'json_schema', 'name': 'machimoa_' + stage,
                           'strict': True, 'schema': schema}},
        'reasoning': {'effort': GPT_REASONING_EFFORT},
        'max_output_tokens': SUMMARY_MAX_TOKENS if stage == 'summary' else TRANSLATION_MAX_TOKENS,
        'service_tier': 'default', 'store': False, 'truncation': 'disabled',
        'timeout': INFERENCE_TIMEOUT_S}


def map_openai_exception(exc: BaseException) -> AiJobError:
    status = getattr(exc, 'status_code', None)
    name = type(exc).__name__
    if name in {'APITimeoutError', 'TimeoutError', 'ReadTimeout'}:
        return AiJobError('ai_timeout')
    if type(status) is int:
        if status in {400, 401, 403, 404, 429}:
            return AiJobError('ai_http_' + str(status))
        if status >= 500:
            return AiJobError('ai_http_5xx')
        if status >= 400:
            return AiJobError('ai_http_4xx')
    return AiJobError('ai_network')


def extract_payload(response: Any) -> object:
    if _get(response, 'status') != 'completed':
        # Incomplete may contain valid-looking partial JSON or reasoning only.
        raise AiJobError('ai_schema_error')
    texts = []
    output = _get(response, 'output')
    if not isinstance(output, list):
        raise AiJobError('ai_schema_error')
    for item in output:
        if _get(item, 'type') == 'reasoning':
            continue
        if (_get(item, 'type') != 'message' or _get(item, 'role') != 'assistant'
                or _get(item, 'status') != 'completed'):
            raise AiJobError('ai_schema_error')
        for part in _get(item, 'content', []):
            if _get(part, 'type') == 'refusal':
                raise AiJobError('ai_refusal')
            if _get(part, 'type') != 'output_text' or not isinstance(_get(part, 'text'), str):
                raise AiJobError('ai_schema_error')
            texts.append(_get(part, 'text'))
    if len(texts) != 1:
        raise AiJobError('ai_schema_error')
    try:
        return json.loads(texts[0])
    except (ValueError, TypeError):
        raise AiJobError('ai_schema_error') from None


class OpenAIAdapter:
    def __init__(self, *, api_key: str | None = None, client: Any = None):
        if client is None:
            if not api_key:
                raise AiJobError('ai_or_enqueue_failed')
            from openai import OpenAI
            client = OpenAI(api_key=api_key, max_retries=0, timeout=INFERENCE_TIMEOUT_S)
        if getattr(client, 'max_retries', None) != 0:
            raise AiJobError('ai_or_enqueue_failed')
        self._client = client
        self._reset_job()

    def _reset_job(self):
        self._create_calls = 0
        self._count_calls = 0
        self._spent_cost_upper_usd = 0.0
        self._translation_input_bound = None
        self._summary_ready = False
        self._translation_attempted = False
        self._usage_records = []

    def _count(self, request: dict) -> int:
        if self._count_calls >= MAX_COUNT_CALLS:
            raise AiJobError('ai_call_budget')
        self._count_calls += 1
        params = {k: request[k] for k in ('model', 'instructions', 'input', 'text', 'reasoning', 'truncation')}
        try:
            result = self._client.responses.input_tokens.count(**params, timeout=COUNT_TIMEOUT_S)
        except Exception as exc:
            raise map_openai_exception(exc) from None
        return _integer(_get(result, 'input_tokens'))

    def _create(self, request: dict, counted_input: int) -> Any:
        if self._create_calls >= MAX_CREATE_CALLS:
            raise AiJobError('ai_call_budget')
        self._create_calls += 1
        try:
            response = self._client.responses.create(**request)
        except Exception as exc:
            raise map_openai_exception(exc) from None
        if (_get(response, 'model') != GPT_MODEL or
                _get(response, 'service_tier', 'default') != 'default'):
            raise AiJobError('ai_schema_error')
        usage = _get(response, 'usage')
        input_tokens = _integer(_get(usage, 'input_tokens'))
        output_tokens = _integer(_get(usage, 'output_tokens'))
        reasoning = _integer(_get(_get(usage, 'output_tokens_details'), 'reasoning_tokens'))
        if (input_tokens > int(counted_input * 1.1) or output_tokens > request['max_output_tokens']
                or reasoning > output_tokens):
            raise AiJobError('ai_cost_bound_breach')
        # Worst-case input pricing covers cache writes; output already includes
        # reasoning, so it must not be added a second time.
        cost = (input_tokens * CACHE_WRITE_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / 1_000_000
        self._spent_cost_upper_usd += cost
        self._usage_records.append({'provider': 'openai', 'model': GPT_MODEL,
            'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'reasoning_tokens': reasoning, 'cost_upper_usd': cost})
        if self._spent_cost_upper_usd > GPT_JOB_USD_CAP:
            raise AiJobError('ai_blocked_cost_cap')
        return response

    def summarize_ko(self, body: str, source_url: str | None, title: str | None = None,
                     *, program: bool | str = False) -> tuple[str, str, str]:
        self._reset_job()
        system = summary_system_prompt(body, program)
        request = build_request(instructions=system,
            user=f'title: {title or ""}\nsource_url: {source_url or ""}\nbody:\n{body}', stage='summary')
        tokens = self._count(request)
        self._translation_input_bound = tokens + SUMMARY_MAX_TOKENS + CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS
        pre_max = bounded_cost(tokens, SUMMARY_MAX_TOKENS) + bounded_cost(
            self._translation_input_bound, TRANSLATION_MAX_TOKENS)
        if pre_max > GPT_JOB_USD_CAP:
            raise AiJobError('ai_blocked_cost_cap')
        content = validate_summary_payload(extract_payload(self._create(request, tokens)))
        self._summary_ready = True
        return content, 'success', GPT_MODEL

    def summarize_program_ko(self, body, source_url, title=None):
        return self.summarize_ko(body, source_url, title, program=True)

    def summarize_myseoul_ko(self, body, source_url, title=None):
        return self.summarize_ko(body, source_url, title, program='myseoul')

    def translate_ja(self, title: str, content_ko: str) -> tuple[str, str, str, str]:
        if not self._summary_ready or self._translation_attempted:
            raise AiJobError('ai_call_budget')
        self._translation_attempted = True
        request = build_request(instructions=translation_system_prompt(),
            user=f'title_ko: {title}\ncontent_ko:\n{content_ko}', stage='translation')
        tokens = self._count(request)
        if tokens > self._translation_input_bound:
            raise AiJobError('ai_cost_bound_breach')
        if self._spent_cost_upper_usd + bounded_cost(tokens, TRANSLATION_MAX_TOKENS) > GPT_JOB_USD_CAP:
            raise AiJobError('ai_blocked_cost_cap')
        title_ja, content_ja = validate_translation_payload(extract_payload(self._create(request, tokens)))
        validate_japanese_output(title_ja, content_ja, korean_source=title + '\n' + content_ko)
        validate_translation_fidelity(title, content_ko, title_ja, content_ja)
        return title_ja, content_ja, 'success', GPT_MODEL
