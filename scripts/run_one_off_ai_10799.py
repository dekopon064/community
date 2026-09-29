"""One-off, revision-pinned AI input for youthcenter_content 48:10799.

The source item remains untouched. A checked-in manifest is the durable input
record even when AI or enqueue fails; successful candidates also carry its
provenance in raw_payload. This command never ingests or publishes content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ingest.ai_claude import ClaudeAdapter
from ingest.ai_provider import PROVIDER_ANTHROPIC, ProviderError, require_configured_provider
from ingest.ai_queue_rpc import enqueue_curation_candidate, is_latest_source_revision
from ingest.ai_worker import AI_PROCESSED, AiWorkerResult, process_ai_jobs
from ingest.models import ClaimedJob
from ingest.rpc_errors import RpcAmbiguous
from ingest.supabase_store import SupabaseIngestStore, create_ingest_client

SOURCE_ID = "youthcenter_content"
EXTERNAL_KEY = "48:10799"
SOURCE_ITEM_ID = "98396243-8907-4c70-b823-066d972c4ac2"
REVISION_HASH = "c43eb4a979733eb688a75aa98fb6d9c28f5af61dc71850494d2d82a580e8476f"
OFFICIAL_URL = (
    "https://gangbuk.familynet.or.kr/web/lay1/program/S1T304C450/"
    "recruitReceipt/view.do?seq=279989"
)
MANIFEST = Path(__file__).resolve().parent / "one_off" / "48-10799.json"
MANIFEST_LABEL = "scripts/one_off/48-10799.json"
MANIFEST_FIELDS = frozenset({
    "source_id", "external_key", "source_item_id", "revision_hash",
    "provided_by", "official_url", "original_plain_text", "input_lines",
    "input_sha256",
})


@dataclass(frozen=True)
class OneOffEvidence:
    body: str
    sha256: str
    provided_by: str
    original_plain_text: str

    def provenance(self, original_source_url: str) -> dict[str, str]:
        return {
            "provided_by": self.provided_by,
            "official_url": OFFICIAL_URL,
            "source_id": SOURCE_ID,
            "external_key": EXTERNAL_KEY,
            "source_item_id": SOURCE_ITEM_ID,
            "revision_hash": REVISION_HASH,
            "input_sha256": self.sha256,
            "manifest": MANIFEST_LABEL,
            "original_source_url": original_source_url,
        }


def load_evidence(path: Path = MANIFEST) -> OneOffEvidence:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("one_off_manifest_unavailable") from exc
    if not isinstance(raw, dict) or set(raw) != MANIFEST_FIELDS:
        raise ValueError("one_off_manifest_schema_mismatch")
    required = {
        "source_id": SOURCE_ID,
        "external_key": EXTERNAL_KEY,
        "source_item_id": SOURCE_ITEM_ID,
        "revision_hash": REVISION_HASH,
        "official_url": OFFICIAL_URL,
        "provided_by": "user_in_build_work_conversation",
        "original_plain_text": "홈페이지 링크: https://buly.kr/jc9Pam",
    }
    if any(raw.get(key) != value for key, value in required.items()):
        raise ValueError("one_off_manifest_target_mismatch")
    lines = raw.get("input_lines")
    if not isinstance(lines, list) or not lines or any(type(line) is not str for line in lines):
        raise ValueError("one_off_input_missing")
    body = "\n".join(lines)
    if len(body) < 300 or all("링크:" in line or not line for line in lines):
        raise ValueError("one_off_input_link_only")
    if not all(marker in body for marker in (
        "서울시 생활권 청년 1인 가구", "2026년 10월 10일", "10월 17일",
        "2026년 9월 15일", "10월 1일 23:00",
    )):
        raise ValueError("one_off_input_facts_missing")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if raw.get("input_sha256") != digest:
        raise ValueError("one_off_input_hash_mismatch")
    return OneOffEvidence(
        body=body,
        sha256=digest,
        provided_by=raw["provided_by"],
        original_plain_text=raw["original_plain_text"],
    )


class OneOffInputStore:
    """Overlay only the exact target's claimed payload, without a DB mutation."""

    def __init__(self, inner: Any, evidence: OneOffEvidence) -> None:
        self.inner = inner
        self.evidence = evidence

    def claim_processing_jobs(self, stage: str, **kwargs: Any) -> list[ClaimedJob]:
        if (
            stage != "ai_enrichment"
            or kwargs.get("limit") != 1
            or kwargs.get("target_source_item_id") != SOURCE_ITEM_ID
            or kwargs.get("target_revision_hash") != REVISION_HASH
        ):
            raise ValueError("one_off_target_required")
        jobs = self.inner.claim_processing_jobs(stage, **kwargs)
        if not jobs:
            return []
        if len(jobs) != 1:
            raise RpcAmbiguous()
        job = jobs[0]
        if (
            job.source_item_id != SOURCE_ITEM_ID
            or job.source_id != SOURCE_ID
            or job.external_key != EXTERNAL_KEY
            or job.revision_hash != REVISION_HASH
            or job.processing_stage != "ai_enrichment"
        ):
            raise RpcAmbiguous()
        original = job.normalized_payload
        if (
            not isinstance(original, dict)
            or original.get("plain_text") != self.evidence.original_plain_text
            or "one_off_ai_input" in original
        ):
            raise RpcAmbiguous()
        original_url = original.get("source_url")
        if original_url != "https://buly.kr/jc9Pam":
            raise RpcAmbiguous()
        overlaid = dict(original)
        overlaid["plain_text"] = self.evidence.body
        overlaid["source_url"] = OFFICIAL_URL
        overlaid["one_off_ai_input"] = self.evidence.provenance(original_url)
        return [replace(job, normalized_payload=overlaid)]

    def complete_processing_job(self, job_id: str, *, worker_id: str) -> Any:
        return self.inner.complete_processing_job(job_id, worker_id=worker_id)

    def fail_processing_job(self, job_id: str, *, worker_id: str, error_code: str) -> Any:
        return self.inner.fail_processing_job(
            job_id, worker_id=worker_id, error_code=error_code
        )


def run_one_off(
    *, store: Any, supabase: Any, evidence: OneOffEvidence,
    summarize_ko: Any, translate_ja: Any, enqueue: Any,
    revision_precheck: Any,
) -> AiWorkerResult:
    def strict_precheck(client: Any, source: str, item: str, revision: str) -> bool:
        if (source, item, revision) != (SOURCE_ID, EXTERNAL_KEY, REVISION_HASH):
            raise RpcAmbiguous()
        # The shared worker treats an existing candidate as success without AI.
        # For this one-off test, fail closed instead of claiming success.
        if revision_precheck(client, source, item, revision):
            raise RpcAmbiguous()
        return False

    def strict_enqueue(client: Any, params: dict[str, Any]) -> dict[str, Any]:
        if (
            params.get("p_source") != SOURCE_ID
            or params.get("p_source_item_id") != EXTERNAL_KEY
            or params.get("p_source_revision_hash") != REVISION_HASH
            or params.get("p_raw_payload", {}).get("one_off_ai_input", {}).get("input_sha256")
            != evidence.sha256
        ):
            raise RpcAmbiguous()
        result = enqueue(client, params)
        if result.get("outcome") != "inserted" or not result.get("candidate_id"):
            raise RpcAmbiguous()
        return result

    return process_ai_jobs(
        OneOffInputStore(store, evidence),
        supabase=supabase,
        summarize_ko=summarize_ko,
        translate_ja=translate_ja,
        enqueue=strict_enqueue,
        revision_precheck=strict_precheck,
        limit=1,
        require_jobs=True,
        target_source_item_id=SOURCE_ITEM_ID,
        target_revision_hash=REVISION_HASH,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Revision-pinned one-off AI input")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        evidence = load_evidence()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"one_off source={SOURCE_ID} item={EXTERNAL_KEY} id={SOURCE_ITEM_ID} "
        f"revision={REVISION_HASH} input_sha256={evidence.sha256} "
        f"manifest={MANIFEST_LABEL}"
    )
    if not args.execute:
        print("one_off execute=false no-op")
        return 0
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
        print("missing_supabase_configuration", file=sys.stderr)
        return 1
    try:
        provider, api_key = require_configured_provider()
        if provider != PROVIDER_ANTHROPIC:
            raise ValueError("unsupported_ai_provider")
        client = create_ingest_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        )
        adapter = ClaudeAdapter(api_key=api_key)
        result = run_one_off(
            store=SupabaseIngestStore(client),
            supabase=client,
            evidence=evidence,
            summarize_ko=adapter.summarize_ko,
            translate_ja=adapter.translate_ja,
            enqueue=enqueue_curation_candidate,
            revision_precheck=is_latest_source_revision,
        )
    except (ProviderError, ValueError) as exc:
        print(getattr(exc, "code", str(exc)), file=sys.stderr)
        return 1
    except Exception:
        print("one_off_execution_failed", file=sys.stderr)
        return 1
    print(
        f"one_off ai={result.status} claimed={result.claimed} "
        f"completed={result.completed} retried={result.retried} "
        f"failed={result.failed} state_unknown={result.state_unknown}"
    )
    return 0 if (
        result.status == AI_PROCESSED
        and result.claimed == result.completed == 1
        and result.retried == result.failed == result.state_unknown == 0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
