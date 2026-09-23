"""Approved summary and Japanese translation rules. No live API or database."""

from __future__ import annotations

import inspect
import unittest
from typing import Any

from ingest.ai_claude import (
    SUMMARY_SYSTEM,
    build_translation_create_kwargs,
    translation_system_prompt,
)
from ingest.ai_errors import AiJobError
from ingest.ai_provider import ALLOWED_PROVIDERS
from ingest.ai_queue_rpc import ENQUEUE_RPC_NAME, FORBIDDEN_ENQUEUE_FIELDS
from ingest.ai_worker import process_ai_jobs
from ingest.region_ja_glossary import (
    approved_ja,
    load_region_entries,
    validate_japanese_output,
)
from test_ingest_ai_worker import SpyStore, _ai_deps, _seed

import ingest.ai_provider as ai_provider


class GlossaryContractTests(unittest.TestCase):
    def test_glossary_has_107_unique_parent_name_pairs(self) -> None:
        entries = load_region_entries()
        pairs = [(entry.parent_ko, entry.ko) for entry in entries]
        self.assertEqual(len(entries), 107)
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_representative_regions_use_approved_japanese(self) -> None:
        expected = {
            ("서울특별시", None): "ソウル特別市",
            ("부산광역시", None): "プサン広域市",
            ("인천광역시", None): "インチョン広域市",
            ("경기도", None): "キョンギ道",
            ("강남구", "서울특별시"): "カンナム区",
            ("제물포구", "인천광역시"): "チェムルポ区",
            ("성남시", "경기도"): "ソンナム市",
            ("양평군", "경기도"): "ヤンピョン郡",
        }
        for (ko, parent_ko), ja in expected.items():
            self.assertEqual(approved_ja(ko, parent_ko), ja)


class JapaneseValidationTests(unittest.TestCase):
    def test_hangul_in_title_or_body_fails(self) -> None:
        with self.assertRaises(AiJobError) as title_error:
            validate_japanese_output("タイトル한", "本文です。", "제목")
        with self.assertRaises(AiJobError) as body_error:
            validate_japanese_output("タイトル", "本文한글です。", "제목")
        self.assertEqual(title_error.exception.code, "ai_schema_error")
        self.assertEqual(body_error.exception.code, "ai_schema_error")

    def test_yen_marks_fail_and_won_passes(self) -> None:
        for mark in ("円", "￥", "¥"):
            with self.assertRaises(AiJobError):
                validate_japanese_output("タイトル", f"10,000{mark}です。", "지원금")
        validate_japanese_output("タイトル", "10,000ウォンです。", "지원금")

    def test_glossary_region_in_source_requires_approved_form(self) -> None:
        source = "강남구 청년을 대상으로 합니다."
        with self.assertRaises(AiJobError):
            validate_japanese_output("タイトル", "江南区の青年が対象です。", source)
        validate_japanese_output("タイトル", "カンナム区の青年が対象です。", source)

    def test_validation_failure_uses_existing_retry_path(self) -> None:
        store = SpyStore()
        _seed(store, 1)

        def translate(title: str, body: str) -> tuple[str, str, str, str]:
            validate_japanese_output("タイトル한", "本文です。", f"{title}\n{body}")
            return ("タイトル한", "本文です。", "success", "claude-sonnet-5")

        result = process_ai_jobs(store, **_ai_deps(translate_ja=translate))
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.retried, 1)
        self.assertEqual(result.failed, 0)
        job = next(row for row in store.jobs.values() if row.error_code)
        self.assertEqual(job.error_code, "ai_schema_error")


class PromptAndCandidatePathTests(unittest.TestCase):
    def test_summary_prompt_requires_sections_and_skips_absent_optional_ones(self) -> None:
        for label in ("[한 줄 요약]", "[대상]", "[기간·상태]", "[주요 내용]", "[신청 방법]"):
            self.assertIn(label, SUMMARY_SYSTEM)
        self.assertIn("[한 줄 요약] and [주요 내용] are required.", SUMMARY_SYSTEM)
        self.assertIn("없는 선택 섹션은 만들지 않는다", SUMMARY_SYSTEM)

    def test_translation_prompt_includes_japanese_sections_and_glossary(self) -> None:
        system = translation_system_prompt()
        for label in ("[要約]", "[対象]", "[期間・状況]", "[主な内容]", "[申請方法]"):
            self.assertIn(label, system)
        self.assertIn("없는 선택 섹션은 만들지 않는다", system)
        self.assertIn("강남구 → カンナム区", system)
        self.assertIn("10,000ウォン", system)
        params = build_translation_create_kwargs(title_ko="제목", content_ko="요약")
        self.assertEqual(params["system"], system)

    def test_successful_result_enqueues_on_pending_candidate_path(self) -> None:
        store = SpyStore()
        _seed(store, 1)
        captured: dict[str, Any] = {}

        def translate(title: str, body: str) -> tuple[str, str, str, str]:
            validate_japanese_output("タイトル", "本文です。", f"{title}\n{body}")
            return ("タイトル", "本文です。", "success", "claude-sonnet-5")

        def enqueue(_supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"outcome": "inserted", "candidate_id": "candidate"}

        result = process_ai_jobs(
            store,
            **_ai_deps(translate_ja=translate, enqueue=enqueue),
        )
        self.assertEqual(result.completed, 1)
        self.assertEqual(captured["p_title_ja"], "タイトル")
        self.assertEqual(captured["p_content_ja"], "本文です。")
        self.assertEqual(captured["p_ai_status_ko"], "success")
        self.assertEqual(captured["p_ai_status_ja"], "success")
        self.assertFalse(FORBIDDEN_ENQUEUE_FIELDS & set(captured))
        self.assertEqual(ENQUEUE_RPC_NAME, "enqueue_curation_candidate")

    def test_provider_stays_anthropic_without_gemini_fallback(self) -> None:
        source = inspect.getsource(ai_provider)
        self.assertNotIn("gemini", source.lower())
        self.assertEqual(ALLOWED_PROVIDERS, frozenset({"anthropic"}))


if __name__ == "__main__":
    unittest.main()
