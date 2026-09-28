"""Offline contract checks for the targeted manual AI canary."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/manual-ai-canary.yml"
MIGRATION = ROOT / "supabase/migrations/20260928000002_ingest_targeted_ai_claim.sql"
ROLLBACK = ROOT / "supabase/rollback/20260928000002_ingest_targeted_ai_claim_down.sql"


class ManualAiCanaryContractTests(unittest.TestCase):
    def test_workflow_is_manual_scoped_and_not_publishing(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("group: machimoa-ingest-production", workflow)
        self.assertIn("environment: machimoa-ingest-production", workflow)
        self.assertIn("--ai-only --execute --ai-limit 1", workflow)
        self.assertIn("--ai-source-item-id babb1e07-a8c8-458e-ba07-10979c1726a6", workflow)
        self.assertIn("--ai-revision-hash 562607cbaaa3d52ac0bcdc1e973826bf1f12dde979eba309a0a264918891c4f0", workflow)
        self.assertNotIn("YOUTH_API_KEY", workflow)
        self.assertNotIn("YOUTH_CONTENT_API_KEY", workflow)
        self.assertNotIn("publish_curation_candidate", workflow)

    def test_target_rpc_rolls_back_mismatch_and_limits_permission(self) -> None:
        migration = MIGRATION.read_text(encoding="utf-8").lower()
        rollback = ROLLBACK.read_text(encoding="utf-8").lower()
        self.assertIn("machimoa_review.claim_processing_jobs(\n    'ai_enrichment', 1,", migration)
        self.assertIn("raise exception 'ai_target_mismatch'", migration)
        self.assertIn("to service_role", migration)
        self.assertIn("from public, anon, authenticated, service_role", migration)
        self.assertIn("drop function if exists public.claim_processing_job_for_source_item", rollback)


if __name__ == "__main__":
    unittest.main()
