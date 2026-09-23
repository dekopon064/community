"""Summary fields copied from labeled AI sections. No live API or database."""

from __future__ import annotations

import unittest
from typing import Any

from ingest.ai_errors import AiJobError
from ingest.ai_worker import (
    JA_SECTION_HEADERS,
    JA_SUMMARY_HEADER,
    KO_SECTION_HEADERS,
    KO_SUMMARY_HEADER,
    SUMMARY_MAX_CHARS,
    extract_summary_section,
    process_ai_jobs,
)
from test_ingest_ai_worker import SpyStore, _ai_deps, _seed


def _ko(body: str, *rest: str) -> str:
    return "\n\n".join((f"{KO_SUMMARY_HEADER}\n{body}", *rest))


def _ja(body: str, *rest: str) -> str:
    return "\n\n".join((f"{JA_SUMMARY_HEADER}\n{body}", *rest))


class SummarySectionTests(unittest.TestCase):
    def test_extracts_korean_and_japanese_summary_bodies(self) -> None:
        korean = _ko(
            "청년 공간 운영을 지원한다.",
            "[대상]\n청년",
            "[주요 내용]\n시설을 대관한다.",
        )
        japanese = _ja(
            "青年空間の運営を支援します。",
            "[対象]\n青年",
            "[主な内容]\n施設を貸し出します。",
        )
        self.assertEqual(
            extract_summary_section(korean, KO_SUMMARY_HEADER, KO_SECTION_HEADERS),
            "청년 공간 운영을 지원한다.",
        )
        self.assertEqual(
            extract_summary_section(japanese, JA_SUMMARY_HEADER, JA_SECTION_HEADERS),
            "青年空間の運営を支援します。",
        )

    def test_trims_surrounding_whitespace_and_same_line_body(self) -> None:
        korean = "[한 줄 요약]   한 줄입니다.   \n\n[주요 내용]\n본문"
        japanese = "[要約]\n\n  一行です。  \n\n[主な内容]\n本文"
        self.assertEqual(
            extract_summary_section(korean, KO_SUMMARY_HEADER, KO_SECTION_HEADERS),
            "한 줄입니다.",
        )
        self.assertEqual(
            extract_summary_section(japanese, JA_SUMMARY_HEADER, JA_SECTION_HEADERS),
            "一行です。",
        )
        self.assertNotIn("[", extract_summary_section(
            korean, KO_SUMMARY_HEADER, KO_SECTION_HEADERS
        ))

    def test_does_not_use_other_optional_sections(self) -> None:
        korean = "\n".join(
            (
                "[대상]",
                "청년만",
                "[기간·상태]",
                "2026년 9월",
                "[한 줄 요약]",
                "한 줄입니다.",
                "[주요 내용]",
                "자세한 내용",
                "[신청 방법]",
                "온라인 접수",
            )
        )
        japanese = "\n".join(
            (
                "[対象]",
                "青年のみ",
                "[期間・状況]",
                "2026年9月",
                "[要約]",
                "一行です。",
                "[主な内容]",
                "詳細です。",
                "[申請方法]",
                "オンライン申請",
            )
        )
        self.assertEqual(
            extract_summary_section(korean, KO_SUMMARY_HEADER, KO_SECTION_HEADERS),
            "한 줄입니다.",
        )
        self.assertEqual(
            extract_summary_section(japanese, JA_SUMMARY_HEADER, JA_SECTION_HEADERS),
            "一行です。",
        )

    def test_missing_empty_or_too_long_uses_schema_error(self) -> None:
        cases = (
            ("[주요 내용]\n본문만 있다.", KO_SUMMARY_HEADER, KO_SECTION_HEADERS),
            ("[한 줄 요약]\n\n[주요 내용]\n본문", KO_SUMMARY_HEADER, KO_SECTION_HEADERS),
            (
                f"[한 줄 요약]\n{'가' * (SUMMARY_MAX_CHARS + 1)}\n\n[주요 내용]\n본문",
                KO_SUMMARY_HEADER,
                KO_SECTION_HEADERS,
            ),
            ("[主な内容]\n本文のみです。", JA_SUMMARY_HEADER, JA_SECTION_HEADERS),
            ("[要約]\n   \n[主な内容]\n本文", JA_SUMMARY_HEADER, JA_SECTION_HEADERS),
            (
                f"[要約]\n{'あ' * (SUMMARY_MAX_CHARS + 1)}",
                JA_SUMMARY_HEADER,
                JA_SECTION_HEADERS,
            ),
        )
        for content, header, headers in cases:
            with self.assertRaises(AiJobError) as caught:
                extract_summary_section(content, header, headers)
            self.assertEqual(caught.exception.code, "ai_schema_error")
        self.assertEqual(
            len(extract_summary_section(
                f"[한 줄 요약]\n{'가' * SUMMARY_MAX_CHARS}",
                KO_SUMMARY_HEADER,
                KO_SECTION_HEADERS,
            )),
            SUMMARY_MAX_CHARS,
        )

    def test_enqueue_receives_summary_fields(self) -> None:
        store = SpyStore()
        _seed(store, 1)
        captured: dict[str, Any] = {}

        def enqueue(_supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"outcome": "inserted", "candidate_id": "candidate"}

        result = process_ai_jobs(store, **_ai_deps(enqueue=enqueue))
        self.assertEqual(result.completed, 1)
        self.assertEqual(captured["p_summary_ko"], "요약입니다.")
        self.assertEqual(captured["p_summary_ja"], "要約です。")
        self.assertNotIn("[한 줄 요약]", captured["p_summary_ko"])
        self.assertNotIn("[要約]", captured["p_summary_ja"])

    def test_missing_section_uses_existing_worker_failure_path(self) -> None:
        store = SpyStore()
        _seed(store, 1)

        def summarize(text: str, url: str | None, title: str | None = None) -> tuple[str, str, str]:
            return ("[주요 내용]\n본문", "success", "claude-sonnet-5")

        result = process_ai_jobs(store, **_ai_deps(summarize_ko=summarize))
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.retried, 1)
        job = next(row for row in store.jobs.values() if row.error_code)
        self.assertEqual(job.error_code, "ai_schema_error")


if __name__ == "__main__":
    unittest.main()
