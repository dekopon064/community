"""Worker adapter for verified ChatGPT-plan OAuth, no API-key fallback."""
from __future__ import annotations

from ingest.ai_claude import (SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM, MYSEOUL_SUMMARY_SYSTEM, summary_system_prompt,
    SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS, INFERENCE_TIMEOUT_S,
    validate_summary_payload, validate_translation_payload, translation_system_prompt)
from ingest.ai_errors import AiJobError
from ingest.ai_openai import GPT_MODEL, build_request, _integer
from ingest.chatgpt_plan_auth import PlanSession
from ingest.chatgpt_plan_protocol import ProbeError, RESOURCE, get_field, read_completed_stream
from ingest.region_ja_glossary import validate_japanese_output
from ingest.rpc_errors import RpcAmbiguous
from ingest.translation_validation import validate_translation_fidelity


class PlanResponseUnknown(RpcAmbiguous):
    def __init__(self, diagnostic):
        super().__init__()
        self.diagnostic = diagnostic


class PlanCommonFailure(AiJobError):
    failure_scope = 'batch'


def plan_request(*, instructions, user, stage):
    request = build_request(instructions=instructions, user=user, stage=stage)
    # The subscription route rejects these paid-API controls. The same output
    # ceilings are checked after completion; this is NOT a server usage cap.
    for key in ('max_output_tokens', 'service_tier', 'truncation'):
        request.pop(key)
    request['stream'] = True
    return request


class ChatGPTPlanAdapter:
    provider = 'openai'
    auth_mode = 'chatgpt_plan'
    billing = 'chatgpt_plan'

    def __init__(self, *, session: PlanSession, client=None):
        if not isinstance(session, PlanSession):
            raise ProbeError('unverified_plan_session')
        session.require_active()
        self._owned_client = client is None
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=session.access_token(), base_url=RESOURCE,
                            max_retries=0, timeout=INFERENCE_TIMEOUT_S)
        if getattr(client, 'max_retries', None) != 0:
            raise AiJobError('ai_or_enqueue_failed')
        if (hasattr(client, 'api_key') and client.api_key != session.access_token() or
                hasattr(client, 'base_url') and str(client.base_url).rstrip('/') != RESOURCE):
            raise AiJobError('ai_or_enqueue_failed')
        if hasattr(client, 'default_headers'):
            authorization = {str(k).lower():v for k,v in client.default_headers.items()}.get('authorization')
            # SDK auth_headers are applied separately; only reject overrides.
            if authorization is not None and authorization != 'Bearer ' + session.access_token():
                raise AiJobError('ai_or_enqueue_failed')
        if hasattr(client, 'auth_headers') and client.auth_headers.get('Authorization') != 'Bearer ' + session.access_token():
            raise AiJobError('ai_or_enqueue_failed')
        self._client, self._session = client, session
        self._blocked = False
        self._reset_job()

    def _reset_job(self):
        self._create_calls = 0
        self._summary_ready = False
        self._translation_attempted = False
        self._usage_records = []

    def release_terminated_attempt(self):
        """Called only after the worker acknowledges a fenced terminal failure.

        Reset the per-item pair ledger, never unblock a transport/auth failure.
        This does not invoke AI or reopen/retry the terminated server attempt.
        """
        if self._blocked:
            raise RpcAmbiguous()
        self._reset_job()

    def close(self):
        try:
            if self._owned_client:
                try:
                    self._client.close()
                finally:
                    self._client.api_key = ''
        finally:
            self._session.clear()
            self._blocked = True

    def _create(self, stage, user, instructions):
        if self._blocked:
            raise RpcAmbiguous()
        try:
            self._session.require_active()
        except ProbeError:
            self._blocked = True
            raise AiJobError('ai_http_401') from None
        if self._create_calls >= 2:
            raise AiJobError('ai_call_budget')
        self._create_calls += 1
        try:
            payload, response = read_completed_stream(self._client,
                plan_request(instructions=instructions, user=user, stage=stage))
        except ProbeError as exc:
            self._blocked = True
            # Unknown completion must not go through a retryable job failure.
            if exc.code in {'plan_timeout', 'plan_transport_unknown', 'stream_missing_completed',
                            'stream_not_completed', 'duplicate_completed_event',
                            'invalid_terminal_output_item', 'conflicting_terminal_output',
                            'invalid_completed_output', 'unexpected_response_model'}:
                raise PlanResponseUnknown({'stage': stage, 'code': exc.code,
                    **(exc.diagnostic or {})}) from None
            mapping = {'plan_http_401':'ai_http_401', 'plan_http_403':'ai_http_403',
                       'plan_http_400':'ai_http_400', 'plan_http_404':'ai_http_404',
                       'subscription_sharing_user_not_eligible':'ai_http_403',
                       'subscription_sharing_unsupported_capability':'ai_http_400',
                       'subscription_sharing_route_not_supported':'ai_http_404',
                       'subscription_sharing_usage_limit_exceeded':'ai_http_429',
                       'subscription_sharing_usage_unavailable':'ai_http_429'}
            if exc.code not in mapping:
                raise PlanResponseUnknown({'stage': stage, 'code': exc.code,
                    **(exc.diagnostic or {})}) from None
            raise AiJobError(mapping[exc.code]) from None
        usage = get_field(response, 'usage')
        try:
            input_tokens = _integer(get_field(usage, 'input_tokens'))
            output_tokens = _integer(get_field(usage, 'output_tokens'))
            reasoning = _integer(get_field(get_field(usage, 'output_tokens_details'), 'reasoning_tokens'))
            total = get_field(usage, 'total_tokens', input_tokens + output_tokens)
            if _integer(total) != input_tokens + output_tokens or reasoning > output_tokens:
                raise AiJobError('ai_schema_error')
        except AiJobError:
            self._blocked = True
            raise PlanCommonFailure('ai_schema_error') from None
        self._usage_records.append({'provider':'openai', 'model':GPT_MODEL,
            'auth_mode':'chatgpt_plan', 'billing':'chatgpt_plan',
            'input_tokens':input_tokens, 'output_tokens':output_tokens,
            'reasoning_tokens':reasoning, 'cost_upper_usd':None})
        limit = SUMMARY_MAX_TOKENS if stage == 'summary' else TRANSLATION_MAX_TOKENS
        if output_tokens > limit:
            raise AiJobError('ai_cost_bound_breach')
        return payload

    def summarize_ko(self, body, source_url, title=None, *, program=False):
        if self._blocked:
            raise RpcAmbiguous()
        user = f'title: {title or ""}\nsource_url: {source_url or ""}\nbody:\n{body}'
        # A new summary starts the next worker job after the preceding pair.
        # Identical text may belong to different fenced items; text is not ID.
        if self._create_calls and not self._translation_attempted:
            raise AiJobError('ai_call_budget')
        self._reset_job()
        instructions = summary_system_prompt(body, program)
        payload = self._create('summary', user, instructions)
        content = validate_summary_payload(payload)
        self._summary_ready = True
        return content, 'success', GPT_MODEL

    def summarize_program_ko(self, body, source_url, title=None):
        return self.summarize_ko(body, source_url, title, program=True)

    def summarize_myseoul_ko(self, body, source_url, title=None):
        return self.summarize_ko(body, source_url, title, program='myseoul')

    def translate_ja(self, title, content_ko):
        if not self._summary_ready or self._translation_attempted:
            raise AiJobError('ai_call_budget')
        self._translation_attempted = True
        payload = self._create('translation', f'title_ko: {title}\ncontent_ko:\n{content_ko}',
                               translation_system_prompt())
        title_ja, content_ja = validate_translation_payload(payload)
        validate_japanese_output(title_ja, content_ja, korean_source=title + '\n' + content_ko)
        validate_translation_fidelity(title, content_ko, title_ja, content_ja)
        return title_ja, content_ja, 'success', GPT_MODEL
