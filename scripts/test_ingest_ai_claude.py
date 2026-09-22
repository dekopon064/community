"""Claude Sonnet 5 adapter tests. 실제 Anthropic API를 호출하지 않는다."""

from __future__ import annotations

import hashlib
import inspect
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ingest.ai_claude import (
    CLAUDE_JOB_USD_CAP,
    CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS,
    COUNT_TIMEOUT_S,
    INFERENCE_TIMEOUT_S,
    SONNET_MODEL,
    SUMMARY_MAX_TOKENS,
    SUMMARY_SCHEMA,
    TRANSLATION_MAX_TOKENS,
    TRANSLATION_SCHEMA,
    ClaudeAdapter,
    assert_request_contract,
    build_summary_create_kwargs,
    build_translation_create_kwargs,
    conservative_cost_usd,
    count_kwargs_from_create,
    translation_prompt_schema_overhead_tokens,
)
from ingest.ai_errors import AI_UNEXPECTED_THINKING, AiJobError

SCRIPTS = Path(__file__).resolve().parent
PROMPTS = SCRIPTS / "ingest" / "claude_prompts"
SCHEMAS = SCRIPTS / "ingest" / "claude_schemas"

SUMMARY_JSON = json.dumps(
    {
        "content_ko": "한국어 요약입니다.",
        "facts": {
            "audience": "",
            "geo_age_income": "",
            "amount_period_deadline": "",
            "how_to_apply": "",
        },
    },
    ensure_ascii=False,
)
TRANSLATION_JSON = json.dumps(
    {"title_ja": "タイトル", "content_ja": "本文です。"},
    ensure_ascii=False,
)


def _usage(input_tokens: int = 10, output_tokens: int = 20, thinking: int = 0) -> Any:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        output_tokens_details=SimpleNamespace(thinking_tokens=thinking),
    )


def _message(text: str, *, stop_reason: str = "end_turn", usage: Any = None) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=usage or _usage(),
    )


def _message_blocks(blocks: list[Any], *, usage: Any | None = None) -> Any:
    return SimpleNamespace(
        content=blocks,
        stop_reason="end_turn",
        usage=usage or _usage(),
    )


class FakeMessages:
    def __init__(self) -> None:
        self.count_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.count_values: list[int] = [100, 120]
        self.messages: list[Any] = [
            _message(SUMMARY_JSON),
            _message(TRANSLATION_JSON),
        ]
        self.count_error: BaseException | None = None
        self.create_error: BaseException | None = None

    def count_tokens(self, **kwargs: Any) -> Any:
        self.count_calls.append(kwargs)
        if self.count_error is not None:
            raise self.count_error
        value = self.count_values[len(self.count_calls) - 1]
        return SimpleNamespace(input_tokens=value)

    def create(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        return self.messages[len(self.create_calls) - 1]


class FakeClient:
    def __init__(self, max_retries: int = 0) -> None:
        self.max_retries = max_retries
        self.messages = FakeMessages()


class HttpError(Exception):
    def __init__(self, status_code: int, name: str = "APIStatusError") -> None:
        self.status_code = status_code
        self.__class__ = type(name, (HttpError,), {})
        super().__init__(name)


class NamedError(Exception):
    pass


def _adapter(client: FakeClient | None = None) -> tuple[ClaudeAdapter, FakeClient]:
    fake = client or FakeClient()
    return ClaudeAdapter(api_key="test-key", client=fake), fake


class ClaudeContractTests(unittest.TestCase):
    def test_copied_prompt_schema_hashes(self) -> None:
        expected = {
            PROMPTS / "summary_system.txt": (
                "353c32bfec0e5bd3e1c68fefd79817161d85daf6d26bee6ca46b38faa2a11b2c"
            ),
            PROMPTS / "translation_system.txt": (
                "d824125b270a1bb5c5a3d7c98b4546d11f476e9e59841b6506acee00277d0519"
            ),
            SCHEMAS / "summary.schema.json": (
                "88fb85a1a5cd4a485e15701d3e708d3568c212f1f605665f7300b0a0efedb093"
            ),
            SCHEMAS / "translation.schema.json": (
                "c52f3c1e1c4c03ec7acd7364cb8e36d7a2d12f2b35c4f256438fac39c7c51d90"
            ),
        }
        for path, digest in expected.items():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual, digest, path.name)

    def test_reserve_exceeds_translation_overhead(self) -> None:
        overhead = translation_prompt_schema_overhead_tokens()
        self.assertGreater(CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS, overhead)

    def test_request_contract_model_thinking_schema_timeout(self) -> None:
        summary = build_summary_create_kwargs(
            title="제목", body="본문", source_url="https://example.invalid"
        )
        translation = build_translation_create_kwargs(
            title_ko="제목", content_ko="요약"
        )
        assert_request_contract(summary, stage="summary")
        assert_request_contract(translation, stage="translation")
        for params in (summary, translation):
            self.assertEqual(params["model"], SONNET_MODEL)
            self.assertEqual(params["thinking"], {"type": "disabled"})
            self.assertNotIn("temperature", params)
            self.assertNotIn("top_p", params)
            self.assertNotIn("top_k", params)
            self.assertNotIn("extra_body", params)
            self.assertEqual(params["timeout"], INFERENCE_TIMEOUT_S)
            fmt = params["output_config"]["format"]
            self.assertEqual(fmt["type"], "json_schema")
        self.assertEqual(summary["max_tokens"], SUMMARY_MAX_TOKENS)
        self.assertEqual(translation["max_tokens"], TRANSLATION_MAX_TOKENS)
        self.assertEqual(summary["output_config"]["format"]["schema"], SUMMARY_SCHEMA)
        self.assertEqual(
            translation["output_config"]["format"]["schema"], TRANSLATION_SCHEMA
        )
        counted = count_kwargs_from_create(summary)
        self.assertNotIn("max_tokens", counted)
        self.assertEqual(counted["timeout"], COUNT_TIMEOUT_S)

    def test_happy_path_two_counts_two_creates(self) -> None:
        adapter, client = _adapter()
        content_ko, status, model = adapter.summarize_ko(
            "본문", "https://example.invalid", title="제목"
        )
        title_ja, content_ja, ja_status, ja_model = adapter.translate_ja("제목", content_ko)
        self.assertEqual(status, "success")
        self.assertEqual(ja_status, "success")
        self.assertEqual(model, SONNET_MODEL)
        self.assertEqual(ja_model, SONNET_MODEL)
        self.assertEqual(content_ko, "한국어 요약입니다.")
        self.assertEqual(title_ja, "タイトル")
        self.assertEqual(len(client.messages.count_calls), 2)
        self.assertEqual(len(client.messages.create_calls), 2)
        for kwargs in client.messages.create_calls:
            self.assertEqual(kwargs["model"], SONNET_MODEL)
            self.assertEqual(kwargs["thinking"], {"type": "disabled"})
            self.assertNotIn("temperature", kwargs)
            self.assertEqual(kwargs["timeout"], INFERENCE_TIMEOUT_S)
        for kwargs in client.messages.count_calls:
            self.assertNotIn("max_tokens", kwargs)
            self.assertEqual(kwargs["timeout"], COUNT_TIMEOUT_S)
        self.assertEqual(client.max_retries, 0)

    def test_pre_max_blocks_all_inference(self) -> None:
        adapter, client = _adapter()
        client.messages.count_values = [8000, 8000]
        with self.assertRaises(AiJobError) as caught:
            adapter.summarize_ko("본문", None, title="제목")
        self.assertEqual(caught.exception.code, "ai_blocked_cost_cap")
        self.assertEqual(len(client.messages.count_calls), 1)
        self.assertEqual(len(client.messages.create_calls), 0)
        self.assertGreater(
            conservative_cost_usd(8000, SUMMARY_MAX_TOKENS)
            + conservative_cost_usd(
                8000 + SUMMARY_MAX_TOKENS + CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS,
                TRANSLATION_MAX_TOKENS,
            ),
            CLAUDE_JOB_USD_CAP,
        )

    def test_post_summary_bound_skips_translation(self) -> None:
        adapter, client = _adapter()
        client.messages.count_values = [100, 5000]
        content_ko, status, model = adapter.summarize_ko("본문", None, title="제목")
        self.assertEqual(status, "success")
        self.assertEqual(model, SONNET_MODEL)
        self.assertEqual(len(client.messages.create_calls), 1)
        with self.assertRaises(AiJobError) as caught:
            adapter.translate_ja("제목", content_ko)
        self.assertEqual(caught.exception.code, "ai_cost_bound_breach")
        self.assertEqual(len(client.messages.create_calls), 1)
        self.assertEqual(len(client.messages.count_calls), 2)

    def test_refusal_schema_timeout_http_errors(self) -> None:
        adapter, client = _adapter()
        client.messages.messages = [_message(SUMMARY_JSON, stop_reason="refusal")]
        with self.assertRaises(AiJobError) as caught:
            adapter.summarize_ko("본문", None, title="제목")
        self.assertEqual(caught.exception.code, "ai_refusal")
        self.assertEqual(len(client.messages.create_calls), 1)

        adapter, client = _adapter()
        client.messages.messages = [_message("{not-json}")]
        with self.assertRaises(AiJobError) as caught:
            adapter.summarize_ko("본문", None, title="제목")
        self.assertEqual(caught.exception.code, "ai_schema_error")

        timeout = type("APITimeoutError", (NamedError,), {})()
        adapter, client = _adapter()
        client.messages.create_error = timeout
        with self.assertRaises(AiJobError) as caught:
            adapter.summarize_ko("본문", None, title="제목")
        self.assertEqual(caught.exception.code, "ai_timeout")

        cases = [
            (401, "AuthenticationError", "ai_http_401"),
            (400, "BadRequestError", "ai_http_400"),
            (403, "PermissionDeniedError", "ai_http_403"),
            (404, "NotFoundError", "ai_http_404"),
            (429, "RateLimitError", "ai_http_429"),
            (503, "InternalServerError", "ai_http_5xx"),
            (418, "APIStatusError", "ai_http_4xx"),
        ]
        for status, name, code in cases:
            adapter, client = _adapter()
            error_type = type(name, (Exception,), {})
            err = error_type("http")
            err.status_code = status
            client.messages.create_error = err
            with self.assertRaises(AiJobError) as caught:
                adapter.summarize_ko("본문", None, title="제목")
            self.assertEqual(caught.exception.code, code)

    def test_text_response_with_zero_thinking_tokens_succeeds(self) -> None:
        adapter, client = _adapter()
        client.messages.messages = [
            _message(SUMMARY_JSON, usage=_usage(thinking=0)),
            _message(TRANSLATION_JSON, usage=_usage(thinking=0)),
        ]
        content_ko, status, model = adapter.summarize_ko(
            "본문", None, title="제목"
        )
        title_ja, content_ja, ja_status, ja_model = adapter.translate_ja(
            "제목", content_ko
        )
        self.assertEqual(status, "success")
        self.assertEqual(ja_status, "success")
        self.assertEqual(model, SONNET_MODEL)
        self.assertEqual(ja_model, SONNET_MODEL)
        self.assertEqual(content_ko, "한국어 요약입니다.")
        self.assertEqual(title_ja, "タイトル")
        self.assertEqual(len(client.messages.create_calls), 2)
        self.assertEqual(len(client.messages.count_calls), 2)

    def test_unexpected_thinking_blocks_and_usage_fail_closed(self) -> None:
        secret = "sk-ant-unexpected-thinking-DoNotLog"
        cases = [
            (
                "thinking-block",
                _message_blocks(
                    [
                        SimpleNamespace(type="thinking", thinking=secret, text=secret),
                        SimpleNamespace(type="text", text=SUMMARY_JSON),
                    ]
                ),
            ),
            (
                "redacted-thinking-block",
                _message_blocks(
                    [
                        SimpleNamespace(
                            type="redacted_thinking", data=secret, text=secret
                        ),
                        SimpleNamespace(type="text", text=SUMMARY_JSON),
                    ]
                ),
            ),
            (
                "usage-thinking-tokens",
                _message(SUMMARY_JSON, usage=_usage(thinking=3)),
            ),
        ]
        for label, message in cases:
            adapter, client = _adapter()
            client.messages.messages = [message]
            with self.assertRaises(AiJobError) as caught:
                adapter.summarize_ko("본문", None, title="제목")
            self.assertEqual(caught.exception.code, AI_UNEXPECTED_THINKING, label)
            self.assertEqual(str(caught.exception), AI_UNEXPECTED_THINKING, label)
            self.assertEqual(
                repr(caught.exception),
                f"AiJobError({AI_UNEXPECTED_THINKING!r})",
                label,
            )
            self.assertNotIn("ai_thinking_tokens", str(caught.exception), label)
            self.assertNotIn(secret, str(caught.exception), label)
            self.assertNotIn(secret, repr(caught.exception), label)
            self.assertNotIn(SUMMARY_JSON, str(caught.exception), label)
            self.assertNotIn(SUMMARY_JSON, repr(caught.exception), label)
            self.assertEqual(len(client.messages.create_calls), 1, label)
            self.assertEqual(len(client.messages.count_calls), 1, label)

    def test_retry_not_disabled_is_rejected(self) -> None:
        with self.assertRaises(AiJobError):
            ClaudeAdapter(api_key="x", client=FakeClient(max_retries=2))

    def test_sampling_forbidden(self) -> None:
        params = build_summary_create_kwargs(title="t", body="b", source_url=None)
        params["temperature"] = 0
        with self.assertRaises(AiJobError) as caught:
            assert_request_contract(params, stage="summary")
        self.assertEqual(caught.exception.code, "ai_sampling_forbidden")

    def test_module_has_no_legacy_provider_imports(self) -> None:
        import ingest.ai_claude as module

        source = inspect.getsource(module)
        self.assertNotIn("fetch_and_save", source)
        self.assertNotIn("google", source)
        self.assertNotIn("genai", source)
        self.assertNotIn("GEMINI", source)


if __name__ == "__main__":
    unittest.main()
