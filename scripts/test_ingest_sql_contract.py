"""ingest SQL 계약 정적 검사. 데이터베이스를 시작하거나 적용하지 않는다."""

from __future__ import annotations

import pathlib
import re
import unittest

from ingest.constants import AI_MAX_ATTEMPTS, LEASE_SECONDS_MAX, LEASE_SECONDS_MIN
from ingest.source_identity import ALLOWED_PERMISSION_TRANSITIONS

ROOT = pathlib.Path(__file__).resolve().parents[1]
OBS = ROOT / "supabase" / "migrations" / "20260913000000_ingest_observation_queue.sql"
PUB = ROOT / "supabase" / "migrations" / "20260913000001_publish_permission_lineage.sql"
OBS_DOWN = ROOT / "supabase" / "rollback" / "20260913000000_ingest_observation_queue_down.sql"
PUB_DOWN = ROOT / "supabase" / "rollback" / "20260913000001_publish_permission_lineage_down.sql"


class IngestSqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.obs = OBS.read_text(encoding="utf-8")
        self.pub = PUB.read_text(encoding="utf-8")
        self.obs_down = OBS_DOWN.read_text(encoding="utf-8")
        self.pub_down = PUB_DOWN.read_text(encoding="utf-8")

    def test_lease_rpc_does_not_take_separate_owner(self) -> None:
        self.assertIn("create function machimoa_review.start_ingest_run(", self.obs)
        self.assertNotRegex(
            self.obs,
            r"start_ingest_run\([\s\S]*p_owner",
        )
        self.assertIn("lease_owner = v_run_id", self.obs)

    def test_upsert_requires_matching_unexpired_lease(self) -> None:
        self.assertIn("v_sync.active_run_id is distinct from p_run_id", self.obs)
        self.assertIn("v_sync.lease_owner is distinct from p_run_id", self.obs)
        self.assertIn("lease_expires_at <= v_now", self.obs)
        self.assertIn("raise exception 'lease_lost'", self.obs)

    def test_checkpoint_updates_after_item_and_job_work(self) -> None:
        upsert = self.obs.split("create function machimoa_review.upsert_source_observations")[1]
        upsert = upsert.split("create function machimoa_review.finish_ingest_run")[0]
        item_pos = upsert.find("insert into machimoa_review.source_items")
        job_pos = upsert.find("insert into machimoa_review.processing_jobs")
        ck_pos = upsert.find("committed_checkpoint = p_next_checkpoint")
        self.assertGreater(job_pos, item_pos)
        self.assertGreater(ck_pos, job_pos)

    def test_finish_does_not_clear_foreign_lease(self) -> None:
        self.assertIn("v_owns := v_sync.lease_owner is not distinct from p_run_id", self.obs)
        self.assertIn("stop_reason = 'lease_lost'", self.obs)
        finish = self.obs.split("create function machimoa_review.finish_ingest_run")[1]
        finish = finish.split("create function machimoa_review.claim_processing_jobs")[0]
        self.assertIn("and st.lease_owner is not distinct from p_run_id", finish)

    def test_bootstrap_complete_only_on_clean_complete_reasons(self) -> None:
        self.assertIn("'bootstrap_range_complete'", self.obs)
        self.assertIn("'empty_batch'", self.obs)
        self.assertIn("'short_batch'", self.obs)
        self.assertIn("p_status = 'complete'", self.obs)

    def test_claim_is_ai_only_with_skip_locked(self) -> None:
        self.assertIn("for update skip locked", self.obs.lower())
        self.assertIn("p_stage is distinct from 'ai_enrichment'", self.obs)
        self.assertIn("v_limit > 10", self.obs)

    def test_human_jobs_cannot_be_completed_by_ai(self) -> None:
        self.assertIn("human_job_not_completable_by_ai", self.obs)

    def test_publication_fk_is_set_null_not_cascade_or_restrict(self) -> None:
        pubs = self.obs.split("create table machimoa_review.source_publications")[1]
        pubs = pubs.split("create table machimoa_review.source_publication_events")[0]
        self.assertIn("on delete set null", pubs.lower())
        self.assertNotIn("on delete cascade", pubs.lower())
        self.assertNotIn("on delete restrict", pubs.lower())

    def test_hard_delete_event_precedes_unlink_and_delete(self) -> None:
        start = self.pub.find(
            "create function machimoa_review.hard_delete_published_curation_contract"
        )
        end = self.pub.find("drop function machimoa_review.publish_curation_candidate")
        body = self.pub[start:end]
        event_pos = body.find("'hard_deleted'")
        unlink_pos = body.find("public_curation_id = null")
        delete_pos = body.find("delete from public.curations")
        self.assertGreater(event_pos, 0)
        self.assertLess(event_pos, unlink_pos)
        self.assertLess(unlink_pos, delete_pos)

    def test_hard_delete_is_not_granted_to_service_role(self) -> None:
        self.assertNotRegex(
            self.pub,
            r"grant execute on function machimoa_review.hard_delete_published_curation_contract",
        )
        self.assertIn(
            "revoke all privileges on function machimoa_review.hard_delete_published_curation_contract",
            self.pub,
        )

    def test_publish_rejects_testing_only_and_maps_legacy_source(self) -> None:
        self.assertIn("publish_not_permitted", self.pub)
        self.assertIn("testing_only", self.pub)
        self.assertIn("canonical_source_id", self.pub)
        self.assertIn("write_publication_lineage", self.pub)

    def test_is_published_default_true(self) -> None:
        self.assertIn("add column if not exists is_published", self.pub.lower())
        self.assertIn("default true", self.pub.lower())

    def test_search_path_fixed_on_definer_functions(self) -> None:
        for sql in (self.obs, self.pub):
            self.assertGreater(sql.count("set search_path = ''"), 3)
            self.assertGreater(sql.count("security definer"), 3)

    def test_service_role_has_no_table_dml_grants(self) -> None:
        self.assertNotIn(
            "grant select on table machimoa_review.source_items",
            self.obs.lower(),
        )
        self.assertIn(
            "revoke all privileges on table machimoa_review.source_items",
            self.obs.lower(),
        )

    def test_rollback_does_not_delete_candidates_or_curations(self) -> None:
        combined = self.obs_down + self.pub_down
        self.assertNotIn("delete from machimoa_review.curation_candidates", combined.lower())
        self.assertNotIn("delete from public.curations", combined.lower())
        self.assertIn("drop column if exists is_published", self.pub_down.lower())

    def test_no_legacy_source_rename(self) -> None:
        self.assertNotIn("update machimoa_review.curation_candidates", self.obs.lower())
        self.assertIn("legacy_curation_source", self.obs)
        self.assertIn("'youthcenter'", self.obs)

    def test_ai_retry_cap_matches_python_constant(self) -> None:
        fail = self.obs.split("create function machimoa_review.fail_processing_job")[1]
        fail = fail.split("create function machimoa_review.set_source_permission")[0]
        self.assertIn(
            f"v_ai_max_attempts pg_catalog.int4 := {AI_MAX_ATTEMPTS}",
            fail,
        )
        self.assertEqual(fail.count("v_ai_max_attempts"), 3)
        self.assertIn("when retry_count + 1 >= v_ai_max_attempts then 'failed'", fail)
        self.assertIn("human_job_not_completable_by_ai", fail)

    def test_claim_excludes_terminal_failed(self) -> None:
        claim = self.obs.split("create function machimoa_review.claim_processing_jobs")[1]
        claim = claim.split("create function machimoa_review.complete_processing_job")[0]
        self.assertIn("j.status = 'queued'", claim)
        self.assertIn("j.status = 'claimed'", claim)
        self.assertNotIn("j.status = 'failed'", claim)

    def test_publication_unique_and_upsert(self) -> None:
        pubs = self.obs.split("create table machimoa_review.source_publications")[1]
        pubs = pubs.split("create table machimoa_review.source_publication_events")[0]
        self.assertIn("unique (source_id, external_key)", pubs)
        self.assertIn("source_publications_source_item_uk", pubs)
        lineage = self.pub.split("create function machimoa_review.write_publication_lineage")[1]
        lineage = lineage.split(
            "create function machimoa_review.hard_delete_published_curation_contract"
        )[0]
        self.assertIn(
            "on conflict on constraint source_publications_source_item_uk",
            lineage.lower(),
        )
        self.assertIn("do update set", lineage.lower())
        event_pos = lineage.find("insert into machimoa_review.source_publication_events")
        snap_pos = lineage.find("insert into machimoa_review.source_publications")
        self.assertGreater(event_pos, 0)
        self.assertGreater(snap_pos, event_pos)

    def test_lease_ttl_is_stored_and_reused(self) -> None:
        start = self.obs.split("create function machimoa_review.start_ingest_run")[1]
        start = start.split("create function machimoa_review.jsonb_has_forbidden_attachment")[0]
        self.assertIn(f"v_lease_seconds < {LEASE_SECONDS_MIN}", start)
        self.assertIn(f"v_lease_seconds > {LEASE_SECONDS_MAX}", start)
        self.assertIn("lease_seconds = v_lease_seconds", start)
        upsert = self.obs.split("create function machimoa_review.upsert_source_observations")[1]
        upsert = upsert.split("create function machimoa_review.finish_ingest_run")[0]
        self.assertNotIn("interval '120 seconds'", upsert)
        self.assertIn("select r.lease_seconds", upsert)
        self.assertNotIn("p_lease_seconds", upsert)

    def test_nested_forbidden_attachment_helper(self) -> None:
        helper = self.obs.split(
            "create function machimoa_review.jsonb_has_forbidden_attachment"
        )[1]
        helper = helper.split("create function machimoa_review.upsert_source_observations")[0]
        self.assertIn("atchfile", helper)
        self.assertIn("jsonb_each", helper)
        self.assertIn("jsonb_array_elements", helper)
        upsert = self.obs.split("create function machimoa_review.upsert_source_observations")[1]
        upsert = upsert.split("create function machimoa_review.finish_ingest_run")[0]
        self.assertIn("jsonb_has_forbidden_attachment(v_item)", upsert)

    def test_set_source_permission_is_atomic_and_not_granted(self) -> None:
        fn = self.obs.split("create function machimoa_review.set_source_permission")[1]
        fn = fn.split("alter function machimoa_review.start_ingest_run")[0]
        update_pos = fn.find("update machimoa_review.ingest_sources")
        event_pos = fn.find("insert into machimoa_review.source_permission_events")
        self.assertGreater(update_pos, 0)
        self.assertGreater(event_pos, update_pos)
        self.assertNotIn("exception when", fn.lower())
        for from_status, allowed in ALLOWED_PERMISSION_TRANSITIONS.items():
            for to_status in allowed:
                self.assertIn(from_status, fn)
                self.assertIn(to_status, fn)
        self.assertNotRegex(
            self.obs,
            r"grant execute on function machimoa_review.set_source_permission",
        )
        self.assertIn(
            "revoke all privileges on function machimoa_review.set_source_permission",
            self.obs,
        )
        self.assertIn("testing_only", self.obs)

    def test_set_source_permission_actor_guard_precedes_mutation(self) -> None:
        fn = self.obs.split("create function machimoa_review.set_source_permission")[1]
        fn = fn.split("alter function machimoa_review.start_ingest_run")[0]
        body = fn.split("as $function$")[1].split("$function$")[0]
        actor_if = re.search(
            r"if\s+v_actor\s+is\s+null\s+or\s+pg_catalog\.char_length\(\s*v_actor\s*\)\s*>\s*128\s+then"
            r"(.*?)"
            r"end if;",
            body,
            flags=re.I | re.S,
        )
        self.assertIsNotNone(actor_if)
        actor_then = actor_if.group(1)
        self.assertIn("raise exception 'invalid actor'", actor_then)
        self.assertNotIn("update ", actor_then.lower())
        self.assertNotIn("insert ", actor_then.lower())

        after_source = body.split("raise exception 'unknown source identity';", 1)[1].lstrip()
        self.assertTrue(after_source.lower().startswith("end if;"))
        rest = after_source.split(";", 1)[1].lstrip()
        self.assertRegex(rest, re.compile(r"^if\s+v_actor\b", re.I))

        update_pos = body.find("update machimoa_review.ingest_sources")
        event_pos = body.find("insert into machimoa_review.source_permission_events")
        actor_pos = actor_if.start()
        self.assertGreater(update_pos, actor_pos)
        self.assertGreater(event_pos, update_pos)

        if_count = len(re.findall(r"(?<!\bend\s)\bif\b", body, flags=re.I))
        end_if_count = len(re.findall(r"\bend\s+if\b", body, flags=re.I))
        self.assertEqual(if_count, end_if_count)
        begin_count = len(re.findall(r"\bbegin\b", body, flags=re.I))
        end_count = len(re.findall(r"\bend\b(?!\s+if)", body, flags=re.I))
        self.assertEqual(begin_count, end_count)
        self.assertNotRegex(
            body,
            re.compile(
                r"end if;\s+raise exception 'invalid actor';\s+end if;",
                re.I,
            ),
        )

        self.assertNotRegex(
            self.obs,
            r"grant execute on function machimoa_review.set_source_permission",
        )
        revoke = self.obs.split(
            "revoke all privileges on function machimoa_review.set_source_permission"
        )[1]
        revoke = revoke.split(";")[0].lower()
        for role in ("service_role", "public", "anon", "authenticated"):
            self.assertIn(role, revoke)

    def test_rollback_restores_previous_publish_function(self) -> None:
        down = self.pub_down
        self.assertIn(
            "apply this file before 20260913000000_ingest_observation_queue_down.sql",
            down.lower(),
        )
        restore = re.search(
            r"create(?:\s+or\s+replace)?\s+function\s+machimoa_review\.publish_curation_candidate\s*\(",
            down,
            flags=re.I,
        )
        self.assertIsNotNone(restore)
        restore_pos = restore.start()
        end_fn = down.find("$function$;", restore_pos)
        self.assertGreater(end_fn, restore_pos)
        body = down[restore_pos:end_fn]
        helper_pos = down.lower().find(
            "drop function if exists machimoa_review.assert_publish_allowed"
        )
        column_pos = down.lower().find("drop column if exists is_published")
        self.assertGreater(helper_pos, restore_pos)
        self.assertGreater(column_pos, restore_pos)
        self.assertGreater(helper_pos, end_fn)
        self.assertIn(
            "reviewed_by must contain 1 to 128 non-whitespace characters",
            body,
        )
        self.assertIn(
            "slug % belongs to a legacy curation; explicit overwrite approval is required",
            body,
        )
        self.assertIn("pg_catalog.uuid", body)
        self.assertIn("pg_catalog.bool", body)
        self.assertNotIn("assert_publish_allowed", body)
        self.assertNotIn("write_publication_lineage", body)
        self.assertNotIn("is_published", body)
        self.assertNotIn("source_publications", body)
        self.assertNotIn("ingest_sources", body)
        self.assertIn("owner to postgres", down[restore_pos:column_pos])
        self.assertIn("from public, anon, authenticated, service_role", down)
        self.assertNotIn("grant execute on function machimoa_review.publish_curation_candidate", down.lower())
        self.assertIn(
            "apply this file after",
            self.obs_down.lower(),
        )
        combined = self.obs_down + self.pub_down
        self.assertNotIn("delete from machimoa_review.curation_candidates", combined.lower())
        self.assertNotIn("delete from public.curations", combined.lower())


if __name__ == "__main__":
    unittest.main()
