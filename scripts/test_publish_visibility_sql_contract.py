"""공개 상태 SQL·앱 필터 계약. 데이터베이스를 적용하지 않는다."""

from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UP = ROOT / "supabase" / "migrations" / "20260927000000_curation_publish_visibility.sql"
DOWN = ROOT / "supabase" / "rollback" / "20260927000000_curation_publish_visibility_down.sql"
APP = ROOT / "app" / "lib" / "curations.ts"
SW = ROOT / "app" / "sw.ts"
NEXT_CONFIG = ROOT / "next.config.ts"
PAGES = (
    ROOT / "app" / "[locale]" / "page.tsx",
    ROOT / "app" / "[locale]" / "info" / "page.tsx",
    ROOT / "app" / "[locale]" / "info" / "[id]" / "page.tsx",
)


class PublishVisibilitySqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.up = UP.read_text(encoding="utf-8").lower()
        self.down = DOWN.read_text(encoding="utf-8").lower()
        self.app = APP.read_text(encoding="utf-8")

    def test_anon_select_requires_published(self) -> None:
        policy = self.up.split('create policy "curations_public_select"')[1]
        policy = policy.split("create function")[0]
        self.assertIn("to anon, authenticated", policy)
        self.assertIn("using (is_published = true)", policy)
        self.assertNotIn("grant ", self.up.split("create function")[0])

    def test_set_published_keeps_identity_and_original_published_at(self) -> None:
        body = self.up.split("$function$")[1]
        self.assertIn("assert_publish_allowed", body)
        self.assertIn("publication_status = 'unpublished'", body)
        self.assertIn("takedown_status = 'unpublished'", body)
        self.assertIn("unpublished_at = v_now", body)
        self.assertIn("publication_status = 'published'", body)
        self.assertIn("takedown_status = 'none'", body)
        self.assertIn("unpublished_at = null", body)
        self.assertIn("'unpublished'", body)
        self.assertIn("'published'", body)
        self.assertNotRegex(body, r"(?m)^\s*published_at\s*=")
        self.assertNotIn("delete from", body)
        self.assertNotRegex(body, r"(?m)^\s*update machimoa_review\.curation_candidates")
        self.assertNotIn("processing_jobs", body)

    def test_function_is_not_granted(self) -> None:
        self.assertIn(
            "revoke all privileges on function machimoa_review.set_curation_published",
            self.up,
        )
        self.assertNotIn("grant execute", self.up)

    def test_legacy_published_candidate_reconstructs_lineage_before_hide(self) -> None:
        body = self.up.split("$function$")[1]
        self.assertIn("c.published_curation_id = p_public_curation_id", body)
        self.assertIn("c.review_status = 'published'", body)
        self.assertIn("select c.* into strict v_legacy_candidate", body)
        self.assertIn("c.published_at = v_curation.updated_at", body)
        self.assertNotIn("limit 1", body)
        self.assertIn("v_legacy_candidate.source_item_id is distinct from v_curation.source_item_id", body)
        for field in (
            "category", "title_ko", "title_ja", "summary_ko", "summary_ja",
            "content_ko", "content_ja", "source_url", "application_deadline_kind",
            "application_deadline_on",
        ):
            self.assertIn(f"c.{field}", body)
            self.assertIn(f"v_curation.{field}", body)
        for field in ("title", "summary", "content"):
            self.assertIn(f"v_curation.{field} is not distinct from v_curation.{field}_ko", body)
        self.assertIn("insert into machimoa_review.source_publications", body)
        self.assertIn("v_legacy_candidate.published_at", body)

    def test_rollback_fail_closed_without_deleting_events(self) -> None:
        self.assertIn("pg_catalog.pg_advisory_xact_lock(20260927, 1)", self.up)
        self.assertIn("pg_catalog.pg_advisory_xact_lock(20260927, 1)", self.down)
        self.assertIn("publish visibility function is no longer installed", self.up)
        self.assertIn("publish visibility requires read committed isolation", self.up)
        self.assertLess(
            self.down.index("set transaction isolation level read committed"),
            self.down.index("pg_catalog.pg_advisory_xact_lock(20260927, 1)"),
        )
        self.assertLess(
            self.down.index("pg_catalog.pg_advisory_xact_lock(20260927, 1)"),
            self.down.index("lock table public.curations in share row exclusive mode"),
        )
        self.assertLess(
            self.down.index("lock table public.curations in share row exclusive mode"),
            self.down.index("where c.is_published = false"),
        )
        self.assertIn("rollback_unpublished_curations_present", self.down)
        self.assertIn("is_published = false", self.down)
        self.assertIn("using (true)", self.down)
        self.assertIn("drop function if exists machimoa_review.set_curation_published", self.down)
        self.assertNotIn("delete from", self.down)
        self.assertNotIn("source_publication_events", self.down)
        self.assertNotIn("drop column", self.down)

    def test_app_reads_filter_published(self) -> None:
        self.assertEqual(self.app.count('.eq("is_published", true)'), 2)

    def test_curation_pages_are_not_served_from_old_caches(self) -> None:
        for path in PAGES:
            source = path.read_text(encoding="utf-8")
            self.assertIn('export const dynamic = "force-dynamic"', source)
            self.assertNotIn("export const revalidate", source)
        sw = SW.read_text(encoding="utf-8")
        self.assertLess(sw.index("pagesNetworkOnly, ...defaultCache"), sw.index("serwist.addEventListeners()"))
        self.assertIn("isSameOriginPageRequest(request, url, sameOrigin)", sw)
        self.assertIn("route.handler.plugins.push(noPageResponseCachePlugin)", sw)
        self.assertIn("route.handler.plugins.push(noPageResponseCacheFirstPlugin)", sw)
        self.assertIn("handler: new NetworkOnly()", sw)
        self.assertIn('"pages-rsc-prefetch"', sw)
        self.assertIn('"pages-rsc"', sw)
        self.assertIn('"pages"', sw)
        self.assertIn("caches.delete(name)", sw)
        self.assertIn("cacheOnNavigation: false", NEXT_CONFIG.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
