"""ingest SQL 계약 정적 검사. 데이터베이스를 시작하거나 적용하지 않는다."""

from __future__ import annotations

import json
import pathlib
import re
import unittest

from ingest.constants import AI_MAX_ATTEMPTS, LEASE_SECONDS_MAX, LEASE_SECONDS_MIN
from ingest.evaluate_gates import (
    CAPITAL_V1_PROFILE,
    CAPITAL_V1_REGION_CODES,
    EVALUATOR_CONTRACT_ID,
    REASON_ATTACHMENT_DEPENDENT,
    REASON_MISSING_SOURCE_URL,
    REASON_REGION_SCOPE_UNKNOWN,
    REASON_RELEVANCE_UNCONFIRMED,
)
from ingest.gate_facts import FORBIDDEN_FACT_KEYS, GATE_FACTS_SCHEMA_VERSION
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
        claim = _latest_fn("machimoa_review", "claim_processing_jobs").lower()
        self.assertIn("skip locked", claim)
        self.assertIn("p_stage is distinct from 'ai_enrichment'", claim)
        self.assertIn("v_limit > 10", claim)
        self.assertIn("ingest_review_decisions", claim)
        self.assertIn("approve_ai", claim)
        self.assertIn("si.revision_hash", claim)
        self.assertIn("si.disposition = 'target'", claim)
        self.assertIn("si.body_usable is true", claim)
        self.assertIn("si.has_source_url is true", claim)
        self.assertIn("'region_review'", claim)
        self.assertIn("'relevance_review'", claim)
        self.assertIn("'content_review'", claim)
        self.assertIn("'product_type_review'", claim)
        self.assertIn("source_item_product_types", claim)
        self.assertNotIn("'relationship_review'", claim)
        self.assertIn("and not exists", claim)
        self.assertIn("claim_lease_until <= v_now", claim)
        self.assertNotIn("claim_lease_until < v_now", claim)
        self.assertIn("for update of j skip locked", claim)

    def test_00000_claim_body_does_not_include_decision_gate(self) -> None:
        claim = self.obs.split("create function machimoa_review.claim_processing_jobs")[1]
        claim = claim.split("create function machimoa_review.complete_processing_job")[0]
        self.assertNotIn("ingest_review_decisions", claim)
        self.assertIn("for update skip locked", claim.lower())

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
        claim = _latest_fn("machimoa_review", "claim_processing_jobs")
        self.assertIn("j.status = 'queued'", claim)
        self.assertIn("j.status = 'claimed'", claim)
        self.assertNotIn("j.status = 'failed'", claim)
        self.assertNotIn("j.status = 'cancelled'", claim)
        self.assertNotIn("j.status = 'completed'", claim)

    def _private_sql(self, name: str, nxt: str) -> str:
        chunk = self.obs.split(f"create function machimoa_review.{name}")[1]
        return chunk.split(f"create function machimoa_review.{nxt}")[0]

    def _private_header_and_body(self, name: str, nxt: str) -> tuple[str, str]:
        chunk = self._private_sql(name, nxt)
        header, rest = chunk.split("as $function$", 1)
        body = rest.split("$function$", 1)[0]
        return header, body

    def _assert_claimed_guarded_update(self, body: str) -> str:
        lowered = body.lower()
        self.assertEqual(lowered.count("update machimoa_review.processing_jobs"), 1)
        update = lowered.split("update machimoa_review.processing_jobs", 1)[1]
        where = update.split("where", 1)[1]
        self.assertIn("status = 'claimed'", where)
        self.assertIn("claimed_by is not distinct from", where)
        self.assertIn("claim_lease_until is not null", where)
        self.assertIn("claim_lease_until >", where)
        self.assertNotRegex(
            update,
            r"where\s+id\s*=\s*p_job_id\s*;",
        )
        return update

    def test_complete_requires_claimed_owner_and_live_lease(self) -> None:
        header, body = self._private_header_and_body(
            "complete_processing_job", "fail_processing_job"
        )
        self.assertIn("p_job_id pg_catalog.uuid", header)
        self.assertIn("p_worker_id pg_catalog.text", header)
        self.assertIn("returns pg_catalog.void", header)
        self.assertIn("security definer", header)
        self.assertIn("set search_path = ''", header)
        self.assertIn("for update", body.lower())
        self.assertIn("raise exception 'job not found'", body)
        self.assertIn("raise exception 'human_job_not_completable_by_ai'", body)
        self.assertIn("v_status is distinct from 'claimed'", body)
        self.assertIn("raise exception 'unexpected_job_status'", body)
        self.assertIn("raise exception 'lease_lost'", body)
        self.assertIn("v_claimed_by is distinct from v_worker", body)
        self.assertIn("v_lease_until is null or v_lease_until <= v_now", body)
        update = self._assert_claimed_guarded_update(body)
        self.assertIn("status = 'completed'", update)
        self.assertIn("claimed_by = null", update)
        self.assertIn("claim_lease_until = null", update)
        self.assertIn("next_retry_at = null", update)
        self.assertNotIn("retry_count = retry_count + 1", body)
        self.assertLess(body.find("for update"), body.lower().find("update machimoa_review.processing_jobs"))
        self.assertLess(
            body.find("v_status is distinct from 'claimed'"),
            body.lower().find("update machimoa_review.processing_jobs"),
        )

    def test_fail_requires_claimed_owner_live_lease_and_single_retry(self) -> None:
        header, body = self._private_header_and_body(
            "fail_processing_job", "set_source_permission"
        )
        self.assertIn("p_job_id pg_catalog.uuid", header)
        self.assertIn("p_worker_id pg_catalog.text", header)
        self.assertIn("p_error_code pg_catalog.text", header)
        self.assertIn("returns pg_catalog.void", header)
        self.assertIn("security definer", header)
        self.assertIn("set search_path = ''", header)
        self.assertIn("for update", body.lower())
        self.assertIn("raise exception 'job not found'", body)
        self.assertIn("raise exception 'human_job_not_completable_by_ai'", body)
        self.assertIn("v_status is distinct from 'claimed'", body)
        self.assertIn("raise exception 'unexpected_job_status'", body)
        self.assertIn("v_claimed_by is distinct from v_worker", body)
        self.assertIn("v_lease_until is null or v_lease_until <= v_now", body)
        self.assertIn("raise exception 'lease_lost'", body)
        update = self._assert_claimed_guarded_update(body)
        self.assertEqual(body.count("retry_count = retry_count + 1"), 1)
        self.assertIn("when retry_count + 1 >= v_ai_max_attempts then 'failed'", update)
        self.assertIn("else 'queued'", update)
        self.assertIn("claimed_by = null", update)
        self.assertIn("claim_lease_until = null", update)
        self.assertLess(
            body.find("v_status is distinct from 'claimed'"),
            body.lower().find("update machimoa_review.processing_jobs"),
        )

    def test_complete_and_fail_keep_owner_acl(self) -> None:
        for name in ("complete_processing_job", "fail_processing_job"):
            self.assertIn(
                f"alter function machimoa_review.{name}",
                self.obs,
            )
            self.assertIn("owner to postgres", self.obs)
            self.assertIn(
                f"revoke all privileges on function machimoa_review.{name}",
                self.obs,
            )
            self.assertIn(
                f"grant execute on function machimoa_review.{name}",
                self.obs,
            )

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


RPC = ROOT / "supabase" / "migrations" / "20260914000000_ingest_public_rpc_adapters.sql"
RPC_DOWN = ROOT / "supabase" / "rollback" / "20260914000000_ingest_public_rpc_adapters_down.sql"
DEC = ROOT / "supabase" / "migrations" / "20260916000000_ingest_review_decisions.sql"
DEC_RPC = ROOT / "supabase" / "migrations" / "20260916000001_ingest_review_decision_rpc_adapters.sql"
DEC_DOWN = ROOT / "supabase" / "rollback" / "20260916000000_ingest_review_decisions_down.sql"
DEC_RPC_DOWN = ROOT / "supabase" / "rollback" / "20260916000001_ingest_review_decision_rpc_adapters_down.sql"
_CREATE_FN = re.compile(
    r"create(?:\s+or\s+replace)?\s+function\s+(machimoa_review|public)\.([a-z0-9_]+)\s*\(",
    re.IGNORECASE,
)


def _migration_sql() -> str:
    files = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def _latest_fn(schema: str, name: str) -> str:
    combined = _migration_sql()
    matches = list(_CREATE_FN.finditer(combined))
    current = [
        match
        for match in matches
        if match.group(1).lower() == schema and match.group(2).lower() == name
    ]
    if not current:
        raise AssertionError(f"missing {schema}.{name}")
    start = current[-1].start()
    following = [match for match in matches if match.start() > start]
    end = following[0].start() if following else len(combined)
    return combined[start:end]


def _function_body(sql: str) -> str:
    parts = sql.split("$function$")
    if len(parts) < 2:
        raise AssertionError("missing function body")
    return parts[1]

_WS = re.compile(r"\s+")
_PRIVATE_GRANT_RE = re.compile(
    r"grant execute\s+on function\s+(machimoa_review\.[a-z0-9_]+)\s*\((.*?)\)\s+"
    r"to\s+service_role\s*;",
    re.IGNORECASE | re.DOTALL,
)
_PRIVATE_REVOKE_RE = re.compile(
    r"revoke all privileges\s+on function\s+(machimoa_review\.[a-z0-9_]+)\s*\((.*?)\)\s+"
    r"from\s+([^;]+);",
    re.IGNORECASE | re.DOTALL,
)
_REQUIRED_REVOKE_ROLES = frozenset({"public", "anon", "authenticated", "service_role"})
_FORBIDDEN_PRIVATE_FNS = (
    "jsonb_has_forbidden_attachment",
    "set_source_permission",
    "assert_publish_allowed",
    "write_publication_lineage",
    "hard_delete_published_curation_contract",
    "publish_curation_candidate",
)


def _normalize_fn_sig(name: str, args: str) -> str:
    types = [
        _WS.sub(" ", part.strip().lower())
        for part in args.split(",")
        if part.strip()
    ]
    return f"{name.lower()}({', '.join(types)})"


def _private_grant_signatures(sql: str) -> set[str]:
    return {
        _normalize_fn_sig(match.group(1), match.group(2))
        for match in _PRIVATE_GRANT_RE.finditer(sql)
    }


def _private_revoke_signatures(sql: str) -> set[str]:
    found: set[str] = set()
    for match in _PRIVATE_REVOKE_RE.finditer(sql):
        roles = {
            part.strip().lower()
            for part in match.group(3).split(",")
            if part.strip()
        }
        if roles != _REQUIRED_REVOKE_ROLES:
            continue
        found.add(_normalize_fn_sig(match.group(1), match.group(2)))
    return found


class IngestPublicRpcAdapterContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.obs = OBS.read_text(encoding="utf-8")
        self.rpc = RPC.read_text(encoding="utf-8")
        self.rpc_down = RPC_DOWN.read_text(encoding="utf-8")

    def _public_fn(self, name: str, nxt: str | None = None) -> str:
        start = f"create function public.{name}"
        body = self.rpc.split(start, 1)[1]
        if nxt is None:
            return body
        return body.split(f"create function public.{nxt}", 1)[0]

    def test_private_complete_still_returns_void(self) -> None:
        private = self.obs.split("create function machimoa_review.complete_processing_job")[1]
        header = private.split("language", 1)[0]
        self.assertIn("returns pg_catalog.void", header)
        self.assertNotIn("create function machimoa_review.complete_processing_job", self.rpc)

    def test_public_complete_returns_text_and_performs_private(self) -> None:
        complete = self._public_fn("complete_processing_job", "fail_processing_job")
        header = complete.split("language", 1)[0]
        self.assertIn("returns pg_catalog.text", header)
        self.assertIn("perform machimoa_review.complete_processing_job", complete)
        self.assertIn("job not found", complete)
        self.assertIn("is distinct from 'completed'", complete)
        self.assertIn("return 'completed'", complete)
        self.assertIn("for update", complete.lower())
        self.assertNotIn("exception when", complete.lower())

    def test_finish_and_fail_wrapper_return_contracts(self) -> None:
        finish = self._public_fn("finish_ingest_run", "claim_processing_jobs")
        self.assertIn("returns table", finish.split("language", 1)[0])
        self.assertIn("status pg_catalog.text", finish)
        self.assertIn("stop_reason pg_catalog.text", finish)
        self.assertIn("run not found", finish)
        self.assertIn("perform machimoa_review.finish_ingest_run", finish)
        fail = self._public_fn("fail_processing_job")
        self.assertIn("returns pg_catalog.text", fail.split("language", 1)[0])
        self.assertIn("job not found", fail)
        self.assertIn("perform machimoa_review.fail_processing_job", fail)
        self.assertIn("'queued', 'failed'", fail)
        self.assertNotIn("exception when", fail.lower())
        self.assertNotIn("return 'completed'", fail)

    def test_get_ingest_source_wrapper(self) -> None:
        get_source = self._public_fn("get_ingest_source", "start_ingest_run")
        self.assertIn("p_source_id pg_catalog.text", get_source)
        for column in (
            "source_id pg_catalog.text",
            "enabled pg_catalog.bool",
            "permission_status pg_catalog.text",
            "legacy_curation_source pg_catalog.text",
        ):
            self.assertIn(column, get_source)
        self.assertIn("machimoa_review.ingest_sources", get_source)

    def test_public_wrappers_owner_search_path_and_acl(self) -> None:
        self.assertEqual(self.rpc.lower().count("security definer"), 7)
        self.assertGreaterEqual(self.rpc.count("set search_path = ''"), 7)
        self.assertEqual(self.rpc.lower().count("owner to postgres"), 7)
        for name in (
            "get_ingest_source",
            "start_ingest_run",
            "upsert_source_observations",
            "finish_ingest_run",
            "claim_processing_jobs",
            "complete_processing_job",
            "fail_processing_job",
        ):
            self.assertIn(f"revoke all privileges on function public.{name}", self.rpc)
            self.assertIn(f"grant execute on function public.{name}", self.rpc)
        self.assertIn("from public, anon, authenticated, service_role", self.rpc)
        self.assertEqual(self.rpc.lower().count("to service_role"), 7)
        self.assertNotIn("to anon", self.rpc.lower())
        self.assertNotIn("to authenticated", self.rpc.lower())
        self.assertNotIn("grant usage on schema machimoa_review", self.rpc.lower())
        self.assertNotIn("grant select on table", self.rpc.lower())
        self.assertNotIn("grant insert on table", self.rpc.lower())
        self.assertNotIn("grant update on table", self.rpc.lower())
        self.assertNotIn("grant delete on table", self.rpc.lower())

    def test_no_permission_or_publish_wrappers(self) -> None:
        lowered = self.rpc.lower()
        self.assertNotIn("set_source_permission", lowered)
        self.assertNotIn("publish_curation", lowered)
        self.assertNotIn("unpublish", lowered)
        self.assertNotIn("create function public.publish", lowered)

    def test_notify_pgrst_on_up_and_down_inside_transaction(self) -> None:
        for sql in (self.rpc, self.rpc_down):
            lowered = sql.lower()
            self.assertIn("notify pgrst, 'reload schema'", lowered)
            self.assertLess(lowered.find("begin"), lowered.find("notify pgrst"))
            self.assertLess(lowered.rfind("notify pgrst"), lowered.rfind("commit"))

    def test_private_service_role_acl_matches_00000_grant_set(self) -> None:
        granted = _private_grant_signatures(self.obs)
        revoked = _private_revoke_signatures(self.rpc)
        restored = _private_grant_signatures(self.rpc_down)
        self.assertEqual(len(granted), 7)
        self.assertEqual(granted, revoked)
        self.assertEqual(revoked, restored)
        names = {sig.split("(", 1)[0] for sig in granted}
        self.assertIn("machimoa_review.canonical_source_id", names)
        self.assertEqual(_private_grant_signatures(self.rpc), set())
        for banned in _FORBIDDEN_PRIVATE_FNS:
            self.assertTrue(
                all(banned not in sig for sig in granted | revoked | restored),
                banned,
            )

    def test_00002_keeps_public_wrapper_grants_without_schema_table_grants(self) -> None:
        for sql in (self.rpc, self.rpc_down):
            lowered = sql.lower()
            self.assertNotIn("grant usage on schema machimoa_review", lowered)
            self.assertNotIn("grant select on table", lowered)
            self.assertNotIn("grant insert on table", lowered)
            self.assertNotIn("grant update on table", lowered)
            self.assertNotIn("grant delete on table", lowered)
            self.assertNotIn("to anon", lowered)
            self.assertNotIn("to authenticated", lowered)
            self.assertNotRegex(lowered, r"grant execute\s+on function\s+[^;]+to\s+public")

    def test_rollback_drops_public_wrappers_only(self) -> None:
        down = self.rpc_down.lower()
        self.assertIn(
            "drop function if exists public.complete_processing_job(pg_catalog.uuid, pg_catalog.text)",
            down,
        )
        self.assertIn("drop function if exists public.get_ingest_source", down)
        self.assertIn("drop function if exists public.start_ingest_run", down)
        self.assertIn("drop function if exists public.upsert_source_observations", down)
        self.assertIn("drop function if exists public.finish_ingest_run", down)
        self.assertIn("drop function if exists public.claim_processing_jobs", down)
        self.assertIn("drop function if exists public.fail_processing_job", down)
        self.assertNotIn("drop function if exists machimoa_review", down)
        self.assertNotIn("drop function machimoa_review", down)
        self.assertNotIn("create function machimoa_review", down)
        self.assertNotIn("create or replace function machimoa_review", down)
        self.assertNotIn("drop table", down)
        self.assertNotIn("delete from machimoa_review.curation_candidates", down)
        self.assertNotIn("delete from public.curations", down)
        self.assertEqual(len(_private_grant_signatures(self.rpc_down)), 7)
        self.assertEqual(down.count("grant execute on function machimoa_review."), 7)


class IngestReviewDecisionSqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dec = DEC.read_text(encoding="utf-8")
        self.rpc = DEC_RPC.read_text(encoding="utf-8")
        self.dec_down = DEC_DOWN.read_text(encoding="utf-8")
        self.rpc_down = DEC_RPC_DOWN.read_text(encoding="utf-8")

    def test_table_columns_unique_fk_rls_and_acl(self) -> None:
        table = self.dec.split("create table machimoa_review.ingest_review_decisions")[1]
        table = table.split("alter table machimoa_review.ingest_review_decisions")[0]
        for column in (
            "source_item_id",
            "revision_hash",
            "review_type",
            "decision",
            "region_scope",
            "audience_relevance",
            "reason_codes",
            "rule_version",
            "reviewer",
            "reviewed_at",
            "memo",
            "created_at",
            "updated_at",
        ):
            self.assertIn(column, table)
        self.assertIn("unique (source_item_id, revision_hash, review_type)", table)
        self.assertIn("references machimoa_review.source_items (id)", table)
        self.assertIn("on delete restrict", table.lower())
        self.assertIn("ingest_review_decisions_approve_ck", table)
        self.assertIn("char_length(memo) <= 500", table)
        self.assertIn("enable row level security", self.dec.lower())
        self.assertIn(
            "revoke all privileges on table machimoa_review.ingest_review_decisions",
            self.dec.lower(),
        )
        self.assertIn("from public, anon, authenticated, service_role", self.dec.lower())
        self.assertNotIn(
            "grant select on table machimoa_review.ingest_review_decisions",
            self.dec.lower(),
        )
        self.assertNotIn(
            "grant insert on table machimoa_review.ingest_review_decisions",
            self.dec.lower(),
        )

    def test_forbidden_payload_columns_absent(self) -> None:
        table = self.dec.split("create table machimoa_review.ingest_review_decisions")[1]
        table = table.split("create function")[0].lower()
        for banned in (
            "plain_text",
            "normalized_payload",
            "source_url",
            "min_fields",
            "attachment",
            "secret",
            "api_key",
            "body",
        ):
            self.assertNotIn(banned, table)

    def test_stage_check_adds_relevance_review_only(self) -> None:
        self.assertIn("'relevance_review'", self.dec)
        self.assertNotIn("'relevance_review_required'", self.dec)
        self.assertNotIn("'resolved_no_action'", self.dec)
        self.assertNotIn("'superseded'", self.dec)

    def test_private_execute_revoked_and_not_granted(self) -> None:
        for sql in (self.dec, self.rpc):
            for name in (
                "apply_ingest_review_decision",
                "resolve_ingest_review_decision",
                "reconcile_queued_ai_job",
                "upsert_source_observations_v2",
            ):
                self.assertIn(
                    f"revoke all privileges on function machimoa_review.{name}",
                    sql,
                )
        self.assertEqual(_private_grant_signatures(self.dec), set())
        self.assertEqual(_private_grant_signatures(self.rpc), set())
        self.assertNotIn(
            "create function public.apply_ingest_review_decision",
            self.dec,
        )
        self.assertNotIn(
            "create function public.apply_ingest_review_decision",
            self.rpc,
        )

    def test_public_wrappers_owner_search_path_and_acl(self) -> None:
        self.assertEqual(self.rpc.lower().count("security definer"), 3)
        self.assertGreaterEqual(self.rpc.count("set search_path = ''"), 3)
        self.assertEqual(self.rpc.lower().count("owner to postgres"), 3)
        for name in (
            "resolve_ingest_review_decision",
            "reconcile_queued_ai_job",
            "upsert_source_observations_v2",
        ):
            self.assertIn(f"revoke all privileges on function public.{name}", self.rpc)
            self.assertIn(f"grant execute on function public.{name}", self.rpc)
            self.assertIn(
                f"create function public.{name}",
                self.rpc,
            )
            fn = _latest_fn("public", name)
            header = fn.split("language", 1)[0]
            self.assertIn("returns table", header.lower())
            self.assertIn("security definer", fn.lower())
            self.assertIn("set search_path = ''", fn)
        self.assertIn("to service_role", self.rpc.lower())
        self.assertNotIn("to anon", self.rpc.lower())
        self.assertNotIn("to authenticated", self.rpc.lower())
        self.assertNotIn("grant usage on schema machimoa_review", self.rpc.lower())
        self.assertNotIn("grant select on table", self.rpc.lower())
        self.assertNotIn("grant insert on table", self.rpc.lower())
        self.assertNotIn("grant update on table", self.rpc.lower())
        self.assertNotIn("grant delete on table", self.rpc.lower())
        self.assertNotIn("set_source_permission", self.rpc.lower())
        self.assertNotIn("publish_curation", self.rpc.lower())
        self.assertNotIn("hard_delete", self.rpc.lower())

    def test_private_functions_owner_and_empty_search_path(self) -> None:
        for name in (
            "apply_ingest_review_decision",
            "resolve_ingest_review_decision",
            "reconcile_queued_ai_job",
            "upsert_source_observations_v2",
            "claim_processing_jobs",
        ):
            fn = _latest_fn("machimoa_review", name)
            header = fn.split("as $function$", 1)[0]
            self.assertIn("security definer", header.lower())
            self.assertIn("set search_path = ''", header)
            self.assertIn(
                f"alter function machimoa_review.{name}",
                self.dec,
            )
            self.assertIn("owner to postgres", self.dec)

    def test_resolve_and_reconcile_state_tokens(self) -> None:
        core = _latest_fn("machimoa_review", "apply_ingest_review_decision")
        resolve = _latest_fn("machimoa_review", "resolve_ingest_review_decision")
        reconcile = _latest_fn("machimoa_review", "reconcile_queued_ai_job")
        self.assertIn("raise exception 'revision_mismatch'", core)
        self.assertIn("raise exception 'decision_conflict'", core)
        self.assertIn("raise exception 'ai_job_claimed'", core)
        self.assertIn("status = 'cancelled'", core)
        self.assertIn("'rejected_non_target'", core)
        self.assertNotIn("status = 'failed'", core.split("begin", 1)[1])
        self.assertNotIn("delete from machimoa_review.source_items", core.lower())
        self.assertNotIn("delete from machimoa_review.ingest_runs", core.lower())
        self.assertIn("apply_ingest_review_decision", resolve)
        self.assertNotIn("raise exception 'decision_conflict'", resolve)
        self.assertIn("keep_with_approve", reconcile)
        self.assertIn("cancel_unfit", reconcile)
        self.assertIn("move_to_review", reconcile)
        self.assertIn("completed_job_not_reconcileable", reconcile)
        self.assertIn("apply_ingest_review_decision", reconcile)
        self.assertNotIn(
            "machimoa_review.resolve_ingest_review_decision",
            reconcile,
        )
        self.assertNotIn("delete from machimoa_review.processing_jobs", reconcile.lower())
        self.assertNotIn("set_source_permission", core.lower())
        self.assertNotIn("assert_publish_allowed", core.lower())
        self.assertNotIn("write_publication_lineage", core.lower())
        self.assertIn("when 'region' then 'region_review'", core)
        self.assertIn("when 'relevance' then 'relevance_review'", core)
        self.assertIn("processing_stage = v_review_stage", core)
        self.assertIn("processing_stage in (", core)
        self.assertIn("disposition = 'target'", core)
        self.assertIn("disposition = 'non_target'", core)
        self.assertIn("and d.review_type = 'region'", core)
        self.assertIn("and d.review_type = 'relevance'", core)
        self.assertIn("'content_review'", core)
        self.assertIn("'product_type_review'", core)
        self.assertNotIn("'relationship_review'", core)
        self.assertIn("when 'content' then 'content_review'", core)
        self.assertIn("if v_review_stage is null then", core)

    def test_v2_matches_v1_signature_and_uses_core(self) -> None:
        v1 = _latest_fn("machimoa_review", "upsert_source_observations")
        v2 = _latest_fn("machimoa_review", "upsert_source_observations_v2")
        public_v2 = _latest_fn("public", "upsert_source_observations_v2")
        v1_header = v1.split("language", 1)[0]
        v2_header = v2.split("language", 1)[0]
        for token in (
            "p_source_id pg_catalog.text",
            "p_run_id pg_catalog.uuid",
            "p_items pg_catalog.jsonb",
            "p_next_checkpoint pg_catalog.jsonb",
            "input_index pg_catalog.int4",
            "external_key pg_catalog.text",
            "outcome pg_catalog.text",
            "duplicate_in_batch pg_catalog.bool",
        ):
            self.assertIn(token, v1_header)
            self.assertIn(token, v2_header)
        self.assertIn("machimoa_review.upsert_source_observations(", v2)
        self.assertIn("apply_ingest_review_decision", v2)
        self.assertIn("ai_job_not_allowed_in_upsert", v2)
        self.assertIn("classifier_metadata_required", v2)
        self.assertIn("classifier_metadata_forbidden", v2)
        self.assertIn("'classifier:'", v2)
        self.assertIn("for update", v2.lower())
        self.assertNotIn("set_source_permission", v2.lower())
        self.assertNotIn("write_publication_lineage", v2.lower())
        self.assertIn("from machimoa_review.upsert_source_observations_v2", public_v2)
        self.assertIn(
            "create function machimoa_review.upsert_source_observations(",
            _migration_sql(),
        )

    def test_v2_result_loop_avoids_ambiguous_output_variables(self) -> None:
        v2 = _latest_fn("machimoa_review", "upsert_source_observations_v2")
        header = v2.split("language", 1)[0]
        self.assertIn(
            "\n  input_index pg_catalog.int4,\n"
            "  external_key pg_catalog.text,\n"
            "  outcome pg_catalog.text,\n"
            "  duplicate_in_batch pg_catalog.bool\n",
            header,
        )
        self.assertNotIn("si.external_key = external_key", v2)
        self.assertNotIn(
            "for input_index, external_key, outcome, duplicate_in_batch in",
            v2,
        )
        self.assertIn("v_upsert_row record", v2)
        self.assertIn("for v_upsert_row in", v2)
        self.assertIn("si.external_key = v_upsert_row.external_key", v2)
        self.assertIn("input_index := v_upsert_row.input_index", v2)
        self.assertIn("external_key := v_upsert_row.external_key", v2)
        self.assertIn("outcome := v_upsert_row.outcome", v2)
        self.assertIn("duplicate_in_batch := v_upsert_row.duplicate_in_batch", v2)
        self.assertIn("p_items -> v_upsert_row.input_index", v2)
        self.assertIn("v_upsert_row.outcome in ('new', 'changed')", v2)
        self.assertIn("v_disp = 'target'", v2)
        self.assertIn("apply_ingest_review_decision", v2)
        self.assertIn("return next", v2)

    def test_rollback_preflight_fail_closed_before_drops(self) -> None:
        for sql in (self.rpc_down, self.dec_down):
            lowered = sql.lower()
            drop_positions = [
                pos
                for pos in (lowered.find("drop function"), lowered.find("drop table"))
                if pos >= 0
            ]
            self.assertTrue(drop_positions)
            first_drop = min(drop_positions)
            lock_decisions = lowered.find(
                "lock table machimoa_review.ingest_review_decisions"
            )
            lock_jobs = lowered.find("lock table machimoa_review.processing_jobs")
            decision_exists = lowered.find(
                "from machimoa_review.ingest_review_decisions"
            )
            relevance_exists = lowered.find(
                "j.processing_stage = 'relevance_review'"
            )
            error = lowered.find("raise exception 'rollback_phase2_data_present'")
            last_error = lowered.rfind("raise exception 'rollback_phase2_data_present'")
            self.assertGreater(lock_decisions, 0)
            self.assertGreater(lock_jobs, lock_decisions)
            self.assertGreater(decision_exists, lock_jobs)
            self.assertGreater(error, decision_exists)
            self.assertGreater(relevance_exists, error)
            self.assertGreater(last_error, relevance_exists)
            self.assertLess(last_error, first_drop)
            self.assertEqual(lowered.count("rollback_phase2_data_present"), 2)
            self.assertNotIn("delete from machimoa_review.source_items", lowered)
            self.assertNotIn("delete from machimoa_review.processing_jobs", lowered)
            self.assertNotIn(
                "delete from machimoa_review.ingest_review_decisions", lowered
            )
            self.assertNotIn("delete from machimoa_review.curation_candidates", lowered)
            self.assertNotIn("delete from public.curations", lowered)
            self.assertNotIn("set processing_stage", lowered)
            self.assertNotIn("processing_stage = 'region_review'", lowered)
            self.assertNotIn("processing_stage = 'content_review'", lowered)
            self.assertNotIn("processing_stage = 'relationship_review'", lowered)
            self.assertNotIn("set_source_permission", lowered)
            self.assertNotIn("write_publication_lineage", lowered)
        restored = self.dec_down.split("add constraint processing_jobs_stage_ck")[1]
        restored = restored.split("commit;")[0]
        self.assertIn("'region_review'", restored)
        self.assertIn("'content_review'", restored)
        self.assertIn("'relationship_review'", restored)
        self.assertIn("'ai_enrichment'", restored)
        self.assertNotIn("'relevance_review'", restored)

    def test_rollback_does_not_delete_candidates_or_curations(self) -> None:
        combined = self.dec_down + self.rpc_down
        self.assertNotIn("delete from machimoa_review.curation_candidates", combined.lower())
        self.assertNotIn("delete from public.curations", combined.lower())
        public_v2 = self.rpc_down.find(
            "drop function if exists public.upsert_source_observations_v2"
        )
        public_resolve = self.rpc_down.find(
            "drop function if exists public.resolve_ingest_review_decision"
        )
        self.assertGreater(public_v2, 0)
        self.assertGreater(public_resolve, public_v2)
        self.assertNotIn("drop function if exists machimoa_review", self.rpc_down.lower())
        private_v2 = self.dec_down.find(
            "drop function if exists machimoa_review.upsert_source_observations_v2"
        )
        private_recon = self.dec_down.find(
            "drop function if exists machimoa_review.reconcile_queued_ai_job"
        )
        private_resolve = self.dec_down.find(
            "drop function if exists machimoa_review.resolve_ingest_review_decision"
        )
        private_apply = self.dec_down.find(
            "drop function if exists machimoa_review.apply_ingest_review_decision"
        )
        self.assertGreater(private_v2, 0)
        self.assertGreater(private_recon, private_v2)
        self.assertGreater(private_resolve, private_recon)
        self.assertGreater(private_apply, private_resolve)
        self.assertIn("drop table if exists machimoa_review.ingest_review_decisions", self.dec_down)
        self.assertIn("create or replace function machimoa_review.claim_processing_jobs", self.dec_down)
        restored = self.dec_down.split(
            "create or replace function machimoa_review.claim_processing_jobs"
        )[1]
        restored = restored.split("drop table")[0]
        self.assertNotIn("ingest_review_decisions", restored)
        self.assertNotIn("upsert_source_observations_v2", restored)

    def test_notify_pgrst_on_adapter_up_and_down(self) -> None:
        for sql in (self.rpc, self.rpc_down):
            lowered = sql.lower()
            self.assertIn("notify pgrst, 'reload schema'", lowered)
            self.assertLess(lowered.find("begin"), lowered.find("notify pgrst"))
            self.assertLess(lowered.rfind("notify pgrst"), lowered.rfind("commit"))


PT = ROOT / "supabase" / "migrations" / "20260918000000_ingest_product_type.sql"
PT_RPC = ROOT / "supabase" / "migrations" / "20260918000001_ingest_product_type_rpc_adapters.sql"
PT_DOWN = ROOT / "supabase" / "rollback" / "20260918000000_ingest_product_type_down.sql"
PT_RPC_DOWN = ROOT / "supabase" / "rollback" / "20260918000001_ingest_product_type_rpc_adapters_down.sql"


class ProductTypeSqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pt = PT.read_text(encoding="utf-8")
        self.rpc = PT_RPC.read_text(encoding="utf-8")
        self.down = PT_DOWN.read_text(encoding="utf-8")
        self.rpc_down = PT_RPC_DOWN.read_text(encoding="utf-8")

    def test_confirmed_values_and_stage_are_split(self) -> None:
        table = self.pt.split("create table machimoa_review.source_item_product_types")[1]
        table = table.split("create function")[0]
        self.assertIn("'event_program'", table)
        self.assertIn("'policy_reference'", table)
        self.assertNotIn("'product_type_review'", table)
        self.assertNotIn("source_kind", table.lower())
        self.assertNotIn("plain_text", table.lower())
        self.assertIn("enable row level security", self.pt.lower())
        self.assertIn(
            "revoke all privileges on table machimoa_review.source_item_product_types",
            self.pt.lower(),
        )
        self.assertIn("'product_type_review'", self.pt)
        self.assertNotIn("'expired'", self.pt)
        self.assertNotIn("product_type_unclassified_after_approve", self.pt)
        self.assertNotIn("review_type", table)

    def test_writers_and_v3_same_txn(self) -> None:
        apply_src = _latest_fn("machimoa_review", "apply_source_item_product_type")
        resolve = _latest_fn("machimoa_review", "resolve_source_item_product_type")
        v3 = _latest_fn("machimoa_review", "upsert_source_observations_v3")
        v2 = _latest_fn("machimoa_review", "upsert_source_observations_v2")
        self.assertIn("insert into machimoa_review.source_item_product_types", apply_src)
        self.assertNotIn("update machimoa_review.source_item_product_types", apply_src)
        self.assertIn("product_type_review", apply_src)
        self.assertIn("apply_source_item_product_type", v3)
        self.assertIn("apply_ingest_review_decision", v3)
        apply_pos = v3.find("apply_source_item_product_type")
        decision_pos = v3.find("apply_ingest_review_decision")
        self.assertGreater(decision_pos, apply_pos)
        self.assertNotIn("apply_source_item_product_type", v2)
        self.assertIn("create function public.upsert_source_observations_v3", self.rpc)
        self.assertIn("create function public.resolve_source_item_product_type", self.rpc)
        self.assertNotIn(
            "create function public.apply_source_item_product_type", self.rpc
        )
        self.assertNotIn(
            "create function public.apply_ingest_review_decision", self.rpc
        )
        self.assertEqual(_private_grant_signatures(self.pt), set())
        self.assertEqual(_private_grant_signatures(self.rpc), set())

    def test_claim_and_apply_and_lease_equality(self) -> None:
        claim = _latest_fn("machimoa_review", "claim_processing_jobs")
        apply = _latest_fn("machimoa_review", "apply_ingest_review_decision")
        ensure = _latest_fn("machimoa_review", "ensure_ai_enrichment_job")
        self.assertIn("source_item_product_types", claim)
        self.assertIn("'product_type_review'", claim)
        self.assertIn("claim_lease_until <= v_now", claim)
        self.assertNotIn("claim_lease_until < v_now", claim)
        self.assertIn("ensure_ai_enrichment_job", apply)
        self.assertIn("'product_type_review'", apply)
        self.assertIn("ai_job_malformed_lease", apply)
        self.assertIn("claim_lease_until <= v_now", apply)
        self.assertIn("status = 'cancelled'", ensure)
        self.assertIn("claim_lease_until <= v_now", ensure)
        self.assertIn("ai_job_malformed_lease", ensure)
        self.assertNotIn("status = 'expired'", ensure)
        self.assertNotIn("insert into machimoa_review.source_item_product_types", apply)
        self.assertNotIn("product_type_review", _latest_fn("machimoa_review", "upsert_source_observations_v2"))

    def test_rollback_fail_closed_acl_and_no_backfill(self) -> None:
        for sql in (self.down, self.rpc_down):
            lowered = sql.lower()
            first_drop = min(
                pos
                for pos in (lowered.find("drop function"), lowered.find("drop table"))
                if pos >= 0
            )
            lock_pt = lowered.find("lock table machimoa_review.source_item_product_types")
            lock_jobs = lowered.find("lock table machimoa_review.processing_jobs")
            error = lowered.find("raise exception 'rollback_product_type_data_present'")
            self.assertGreater(lock_pt, 0)
            self.assertGreater(lock_jobs, lock_pt)
            self.assertGreater(error, lock_jobs)
            self.assertLess(error, first_drop)
            self.assertEqual(lowered.count("rollback_product_type_data_present"), 2)
            self.assertNotIn("delete from machimoa_review.source_items", lowered)
            self.assertNotIn("delete from machimoa_review.curation_candidates", lowered)
            self.assertNotIn("delete from public.curations", lowered)
            self.assertNotIn("delete from machimoa_review.ingest_review_decisions", lowered)
            self.assertNotIn("status in ('queued', 'claimed', 'completed', 'failed', 'cancelled', 'expired')", lowered)
            self.assertNotIn("'expired'", lowered.split("begin;")[1] if "begin;" in lowered else lowered)
        self.assertIn("drop function if exists public.upsert_source_observations_v3", self.rpc_down)
        self.assertNotIn("drop function if exists machimoa_review", self.rpc_down.lower())
        self.assertIn("create or replace function machimoa_review.apply_ingest_review_decision", self.down)
        self.assertLess(
            self.down.find("create or replace function machimoa_review.apply_ingest_review_decision"),
            self.down.find("drop function if exists machimoa_review.ensure_ai_enrichment_job"),
        )
        restored_claim = self.down.split(
            "create or replace function machimoa_review.claim_processing_jobs"
        )[1].split("create or replace function")[0]
        self.assertIn("ingest_review_decisions", restored_claim)
        self.assertNotIn("source_item_product_types", restored_claim)
        self.assertIn("claim_lease_until < v_now", restored_claim)
        self.assertIn("'relevance_review'", self.down.split("add constraint processing_jobs_stage_ck")[1])
        self.assertNotIn(
            "'product_type_review'",
            self.down.split("add constraint processing_jobs_stage_ck")[1].split("drop table")[0],
        )
        self.assertNotIn("backfill", self.pt.lower())
        self.assertNotIn("phase 3", self.pt.lower())
        self.assertIn("notify pgrst, 'reload schema'", self.rpc.lower())
        self.assertIn("notify pgrst, 'reload schema'", self.rpc_down.lower())


GF = ROOT / "supabase" / "migrations" / "20260921000000_ingest_gate_facts.sql"
GF_RPC = ROOT / "supabase" / "migrations" / "20260921000001_ingest_gate_facts_rpc_adapters.sql"
GF_DOWN = ROOT / "supabase" / "rollback" / "20260921000000_ingest_gate_facts_down.sql"
GF_RPC_DOWN = ROOT / "supabase" / "rollback" / "20260921000001_ingest_gate_facts_rpc_adapters_down.sql"
EVALUATOR_FIXTURE = (
    ROOT / "scripts" / "ingest" / "fixtures" / "capital_v1_evaluator.json"
)


class GateFactsSqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gf = GF.read_text(encoding="utf-8")
        self.rpc = GF_RPC.read_text(encoding="utf-8")
        self.down = GF_DOWN.read_text(encoding="utf-8")
        self.rpc_down = GF_RPC_DOWN.read_text(encoding="utf-8")

    def test_nullable_versioned_facts_not_empty_object_default(self) -> None:
        self.assertIn("add column gate_facts pg_catalog.jsonb", self.gf)
        self.assertIn("add column assessment_schema_version pg_catalog.text", self.gf)
        self.assertIn("add column evaluated_profile pg_catalog.text", self.gf)
        self.assertIn("add column evaluated_at pg_catalog.timestamptz", self.gf)
        self.assertNotIn("gate_facts jsonb not null default '{}'", self.gf.lower())
        self.assertNotIn("default '{}'::pg_catalog.jsonb", self.gf.lower())
        self.assertIn("source_item_product_types_gate_state_ck", self.gf)
        self.assertIn("gate_facts is null", self.gf)
        self.assertIn("gate_facts <> '{}'::pg_catalog.jsonb", self.gf)
        self.assertIn("'living_guide'", self.gf)
        self.assertIn("product_type in ('event_program', 'policy_reference', 'living_guide')", self.gf)
        for key in FORBIDDEN_FACT_KEYS:
            self.assertIn(f"'{key}'", self.gf)

    def test_v3_product_type_target_contract_unchanged(self) -> None:
        apply_v3 = _latest_fn("machimoa_review", "apply_source_item_product_type")
        resolve_pt = _latest_fn("machimoa_review", "resolve_source_item_product_type")
        v3 = _latest_fn("machimoa_review", "upsert_source_observations_v3")
        v2 = _latest_fn("machimoa_review", "upsert_source_observations_v2")
        self.assertIn("if v_item.disposition is distinct from 'target' then", apply_v3)
        self.assertIn("content_product_type_locked", apply_v3)
        self.assertNotIn("living_guide", apply_v3)
        self.assertNotIn("gate_facts", apply_v3)
        self.assertNotIn("p_gate_facts", resolve_pt)
        self.assertIn("'living_guide'", resolve_pt)
        self.assertNotIn("content_product_type_locked", _function_body(resolve_pt))
        self.assertIn("apply_source_item_product_type", v3)
        self.assertIn("apply_ingest_review_decision", v3)
        self.assertNotIn("evaluate_source_item_gates", v3)
        self.assertNotIn("upsert_source_observations_v4", v3)
        self.assertNotIn("apply_source_item_product_type", v2)

    def test_v4_upsert_persists_proposal_and_uses_db_evaluator(self) -> None:
        v4 = _latest_fn("machimoa_review", "upsert_source_observations_v4")
        apply_v4 = _latest_fn("machimoa_review", "apply_source_item_product_type_v4")
        self.assertIn("machimoa_review.upsert_source_observations(", v4)
        self.assertIn("apply_source_item_product_type_v4", v4)
        self.assertIn("apply_source_item_evaluation", v4)
        self.assertNotIn("apply_source_item_product_type(", v4)
        self.assertNotIn("apply_ingest_review_decision", v4)
        self.assertNotIn("approve_ai", v4)
        self.assertNotIn("classifier_metadata_required", v4)
        self.assertNotIn("product_type_metadata_forbidden", v4)
        self.assertNotIn("product_type_metadata_required", v4)
        self.assertIn("classifier_metadata_forbidden", v4)
        self.assertIn("'living_guide'", apply_v4)
        self.assertNotIn("content_product_type_locked", apply_v4)
        self.assertNotIn("disposition is distinct from 'target'", apply_v4)
        self.assertIn("'capital_v1'", apply_v4)
        self.assertIn("'gate-facts-v1'", apply_v4)

    def test_python_evaluator_mirror_tokens_and_fixture_parity(self) -> None:
        evaluator = _latest_fn("machimoa_review", "evaluate_source_item_gates")
        validate = _latest_fn("machimoa_review", "validate_gate_facts")
        self.assertIn(EVALUATOR_CONTRACT_ID, evaluator)
        self.assertIn(f"'{CAPITAL_V1_PROFILE}'", evaluator)
        self.assertIn(f"'{GATE_FACTS_SCHEMA_VERSION}'", validate)
        self.assertNotIn("delivery_mode", evaluator)
        self.assertNotIn("activity_location", evaluator)
        self.assertNotIn("nationwide_or_online", evaluator)
        self.assertNotIn("approve_ai", evaluator)
        self.assertIn(
            "create or replace function machimoa_review.evaluate_source_item_gates",
            evaluator,
        )
        body = _function_body(evaluator)
        self.assertNotIn("'product_type_review'", body)
        self.assertNotIn("'region_review'", body)
        self.assertNotIn("'relevance_review'", body)
        self.assertIn("'content_review'", body)
        self.assertIn("delivery_mode", validate)
        for code in sorted(CAPITAL_V1_REGION_CODES):
            self.assertIn(f"'{code}'", evaluator)
        for token in (
            REASON_ATTACHMENT_DEPENDENT,
            REASON_MISSING_SOURCE_URL,
            REASON_REGION_SCOPE_UNKNOWN,
            REASON_RELEVANCE_UNCONFIRMED,
            "passed",
            "failed",
            "review_required",
            "not_applicable",
            "attachment_dependent",
            "non_target",
            "observe_only",
            "region_review_required",
            "target",
            "living_guide",
            "policy_reference",
            "event_program",
        ):
            self.assertIn(f"'{token}'", evaluator)
        cases = json.loads(EVALUATOR_FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 14)
        for case in cases:
            self.assertIn(f"'{case['expect_disposition']}'", evaluator)
            self.assertIn(f"'{case['expect_region_status']}'", evaluator)
            self.assertIn(f"'{case['expect_audience_status']}'", evaluator)
            for stage in case["expect_job_stages"]:
                self.assertIn(f"'{stage}'", evaluator)

    def test_ensure_ai_and_claim_split_legacy_and_v1_paths(self) -> None:
        ensure = _latest_fn("machimoa_review", "ensure_ai_enrichment_job")
        claim = _latest_fn("machimoa_review", "claim_processing_jobs")
        for body in (ensure, claim):
            self.assertIn("gate_facts is null", body)
            self.assertIn("gate_facts <> '{}'::pg_catalog.jsonb", body)
            self.assertIn("'capital_v1'", body)
            self.assertIn("'gate-facts-v1'", body)
            self.assertIn("approve_ai", body)
            self.assertIn("ingest_review_decisions", body)
            self.assertIn("source_item_product_types", body)
            self.assertIn("claim_lease_until <= v_now", body)
            self.assertNotIn("claim_lease_until < v_now", body)
        self.assertIn("v_legacy_ready or v_v1_ready", ensure)
        self.assertIn("ai_job_malformed_lease", ensure)
        self.assertIn("status = 'cancelled'", ensure)
        self.assertNotIn("status = 'expired'", ensure)
        self.assertIn("gate_facts_row_is_complete_v1", claim)
        self.assertIn("gate_facts_row_is_complete_v1", ensure)
        complete = _latest_fn("machimoa_review", "gate_facts_row_is_complete_v1")
        self.assertIn("p_gate_facts = '{}'::pg_catalog.jsonb", complete)
        self.assertIn("'gate-facts-v1'", complete)
        self.assertIn("p_expected_profile", complete)

    def test_ensure_and_claim_v1_recheck_evaluator_target(self) -> None:
        ensure = _function_body(_latest_fn("machimoa_review", "ensure_ai_enrichment_job"))
        claim = _function_body(_latest_fn("machimoa_review", "claim_processing_jobs"))
        self.assertEqual(ensure.count("machimoa_review.evaluate_source_item_gates("), 1)
        self.assertEqual(claim.count("machimoa_review.evaluate_source_item_gates("), 1)
        legacy_ensure = ensure.split("v_legacy_ready :=")[1].split("v_v1_ready :=")[0]
        v1_ensure = ensure.split("v_v1_ready :=")[1].split("v_ready :=")[0]
        self.assertNotIn("evaluate_source_item_gates", legacy_ensure)
        self.assertIn("approve_ai", legacy_ensure)
        self.assertIn("gate_facts is null", legacy_ensure)
        self.assertIn("evaluate_source_item_gates", v1_ensure)
        self.assertIn("ev.disposition is not distinct from 'target'", v1_ensure)
        self.assertRegex(
            v1_ensure,
            r"evaluate_source_item_gates\(\s*"
            r"v_item\.body_usable,\s*"
            r"v_item\.has_source_url,\s*"
            r"v_item\.attachment_present,\s*"
            r"pt\.product_type,\s*"
            r"pt\.reason_codes,\s*"
            r"pt\.gate_facts\s*\)",
        )
        claim_legacy = claim.split("or (")[0]
        self.assertNotIn("evaluate_source_item_gates", claim_legacy)
        self.assertIn("gate_facts is null", claim)
        self.assertIn("approve_ai", claim)
        self.assertIn("ev.disposition is not distinct from 'target'", claim)
        self.assertRegex(
            claim,
            r"evaluate_source_item_gates\(\s*"
            r"si\.body_usable,\s*"
            r"si\.has_source_url,\s*"
            r"si\.attachment_present,\s*"
            r"pt\.product_type,\s*"
            r"pt\.reason_codes,\s*"
            r"pt\.gate_facts\s*\)",
        )
        restored_ensure = self.down.split(
            "create or replace function machimoa_review.ensure_ai_enrichment_job"
        )[1].split("drop function")[0]
        restored_claim = self.down.split(
            "create or replace function machimoa_review.claim_processing_jobs"
        )[1].split("create or replace function")[0]
        self.assertNotIn("evaluate_source_item_gates", restored_ensure)
        self.assertNotIn("evaluate_source_item_gates", restored_claim)

    def test_resolve_gate_facts_is_separate_from_product_type_rpc(self) -> None:
        resolve_facts = _latest_fn("machimoa_review", "resolve_source_item_gate_facts")
        apply_facts = _latest_fn("machimoa_review", "apply_source_item_gate_facts")
        resolve_pt = _latest_fn("machimoa_review", "resolve_source_item_product_type")
        self.assertIn("apply_source_item_gate_facts", resolve_facts)
        self.assertIn("product_type_not_confirmed", apply_facts)
        self.assertIn("apply_source_item_evaluation", apply_facts)
        self.assertIn("ai_job_claimed", apply_facts)
        self.assertIn("invalid_assessment_schema_version", apply_facts)
        self.assertNotIn("p_gate_facts", resolve_pt)
        self.assertIn("'content_review'", resolve_facts)
        self.assertIn("create function public.resolve_source_item_gate_facts", self.rpc)
        self.assertIn("create function public.upsert_source_observations_v4", self.rpc)
        self.assertNotIn("create function public.apply_source_item_gate_facts", self.rpc)
        self.assertNotIn("create function public.evaluate_source_item_gates", self.rpc)
        self.assertNotIn("create function public.apply_source_item_product_type_v4", self.rpc)
        self.assertNotIn(
            "create function public.apply_source_item_product_type", self.rpc
        )
        self.assertEqual(_private_grant_signatures(self.gf), set())
        self.assertEqual(_private_grant_signatures(self.rpc), set())
        self.assertIn("to service_role", self.rpc.lower())
        self.assertNotIn("to anon", self.rpc.lower())
        self.assertNotIn("to authenticated", self.rpc.lower())
        self.assertNotIn("grant select on table", self.rpc.lower())
        self.assertIn("set search_path = ''", resolve_facts)
        self.assertIn("security definer", resolve_facts.lower())

    def test_rollback_fail_closed_and_restores_legacy_ai_predicates(self) -> None:
        for sql in (self.down, self.rpc_down):
            lowered = sql.lower()
            first_drop = min(
                pos
                for pos in (lowered.find("drop function"), lowered.find("drop table"))
                if pos >= 0
            )
            lock_pt = lowered.find("lock table machimoa_review.source_item_product_types")
            lock_jobs = lowered.find("lock table machimoa_review.processing_jobs")
            error = lowered.find("raise exception 'rollback_gate_facts_data_present'")
            self.assertGreater(lock_pt, 0)
            self.assertGreater(lock_jobs, lock_pt)
            self.assertGreater(error, lock_jobs)
            self.assertLess(error, first_drop)
            self.assertEqual(lowered.count("rollback_gate_facts_data_present"), 2)
            self.assertNotIn("delete from machimoa_review.source_items", lowered)
            self.assertNotIn("delete from machimoa_review.curation_candidates", lowered)
            self.assertNotIn("delete from public.curations", lowered)
            self.assertNotIn("delete from machimoa_review.ingest_review_decisions", lowered)
            self.assertNotIn("backfill", lowered)
            self.assertNotIn("phase 3", lowered)
        self.assertIn(
            "drop function if exists public.upsert_source_observations_v4",
            self.rpc_down,
        )
        self.assertIn(
            "drop function if exists public.resolve_source_item_gate_facts",
            self.rpc_down,
        )
        self.assertNotIn("drop function if exists machimoa_review", self.rpc_down.lower())
        restored_claim = self.down.split(
            "create or replace function machimoa_review.claim_processing_jobs"
        )[1].split("create or replace function")[0]
        self.assertIn("approve_ai", restored_claim)
        self.assertIn("source_item_product_types", restored_claim)
        self.assertNotIn("capital_v1", restored_claim)
        self.assertNotIn("gate-facts-v1", restored_claim)
        restored_ensure = self.down.split(
            "create or replace function machimoa_review.ensure_ai_enrichment_job"
        )[1].split("drop function")[0]
        self.assertIn("approve_ai", restored_ensure)
        self.assertNotIn("v_v1_ready", restored_ensure)
        self.assertNotIn("capital_v1", restored_ensure)
        self.assertIn("drop column if exists gate_facts", self.down)
        self.assertIn(
            "check (product_type in ('event_program', 'policy_reference'))",
            self.down,
        )
        self.assertIn("notify pgrst, 'reload schema'", self.rpc.lower())
        self.assertIn("notify pgrst, 'reload schema'", self.rpc_down.lower())
        self.assertNotIn("backfill", self.gf.lower())
        self.assertNotIn("phase 3", self.gf.lower())


MIN_WF = ROOT / "supabase" / "migrations" / "20260923000000_ingest_min_review_workflow.sql"
MIN_WF_DOWN = (
    ROOT / "supabase" / "rollback" / "20260923000000_ingest_min_review_workflow_down.sql"
)


class MinReviewWorkflowSqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = MIN_WF.read_text(encoding="utf-8")
        self.down = MIN_WF_DOWN.read_text(encoding="utf-8")

    def test_replaces_only_existing_private_functions(self) -> None:
        created = [
            match.group(2)
            for match in _CREATE_FN.finditer(self.sql)
            if match.group(1).lower() == "machimoa_review"
        ]
        self.assertEqual(
            created,
            [
                "evaluate_source_item_gates",
                "resolve_source_item_product_type",
                "resolve_source_item_gate_facts",
            ],
        )
        self.assertEqual(self.sql.lower().count("create or replace function"), 3)
        self.assertNotIn("create table", self.sql.lower())
        self.assertNotIn("create function public.", self.sql.lower())
        self.assertNotIn("grant execute", self.sql.lower())
        self.assertEqual(_private_grant_signatures(self.sql), set())
        self.assertIn(
            "revoke all privileges on function machimoa_review.evaluate_source_item_gates",
            self.sql,
        )
        self.assertNotIn("apply_source_item_human_assessment", self.sql)
        self.assertNotIn("insert into machimoa_review.ingest_review_decisions", self.sql)

    def test_rollback_restores_origin_bodies_without_data_delete(self) -> None:
        self.assertIn("content_product_type_locked", self.down)
        restored_eval = _function_body(
            self.down.split("create or replace function machimoa_review.evaluate_source_item_gates")[1]
        )
        self.assertIn("'product_type_review'", restored_eval)
        self.assertIn("'region_review'", restored_eval)
        self.assertIn("'relevance_review'", restored_eval)
        lowered = self.down.lower()
        self.assertNotIn("delete from machimoa_review.ingest_review_decisions", lowered)
        self.assertNotIn("delete from machimoa_review.processing_jobs", lowered)
        self.assertNotIn("delete from public.curations", lowered)
        self.assertEqual(_private_grant_signatures(self.down), set())


CLOSE = ROOT / "supabase" / "migrations" / "20260924000000_ingest_content_review_close.sql"
CLOSE_DOWN = (
    ROOT / "supabase" / "rollback" / "20260924000000_ingest_content_review_close_down.sql"
)


class ContentReviewCloseSqlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = CLOSE.read_text(encoding="utf-8")
        self.down = CLOSE_DOWN.read_text(encoding="utf-8")

    def test_reuses_existing_functions_without_new_surface(self) -> None:
        created = [
            (match.group(1).lower(), match.group(2))
            for match in _CREATE_FN.finditer(self.sql)
        ]
        self.assertEqual(
            created,
            [
                ("machimoa_review", "apply_ingest_review_decision"),
                ("machimoa_review", "apply_source_item_evaluation"),
            ],
        )
        lowered = self.sql.lower()
        self.assertNotIn("create table", lowered)
        self.assertNotIn("add column", lowered)
        self.assertNotIn("create function public.", lowered)
        self.assertNotIn("grant execute", lowered)
        self.assertNotIn("grant ", lowered)
        self.assertEqual(_private_grant_signatures(self.sql), set())
        self.assertIn(
            "check (review_type in ('region', 'relevance', 'content'))",
            self.sql,
        )
        apply = _function_body(
            self.sql.split("create or replace function machimoa_review.apply_ingest_review_decision")[1]
        )
        self.assertIn("when 'content' then 'content_review'", apply)
        self.assertIn("raise exception 'invalid_decision'", apply)
        self.assertIn("raise exception 'insufficient_evidence_required'", apply)
        self.assertIn("raise exception 'ai_job_claimed'", apply)
        self.assertIn("raise exception 'revision_mismatch'", apply)
        self.assertIn("disposition = 'non_target'", apply)
        before_write = apply.split("insert into machimoa_review.ingest_review_decisions", 1)[0]
        self.assertIn("raise exception 'content_review_not_open'", before_write)
        self.assertIn("raise exception 'curation_candidate_exists'", before_write)
        self.assertIn("processing_stage = 'content_review'", before_write)
        self.assertIn("status in ('queued', 'claimed')", before_write)
        self.assertIn("for update", before_write.lower())
        self.assertNotIn("publish_curation_candidate", self.sql)
        self.assertNotIn("update machimoa_review.curation_candidates", self.sql.lower())
        self.assertNotIn("delete from machimoa_review.curation_candidates", self.sql.lower())
        evaluation = _function_body(
            self.sql.split("create or replace function machimoa_review.apply_source_item_evaluation")[1]
        )
        self.assertIn("review_type = 'content'", evaluation)
        self.assertIn("'insufficient_evidence' = any(d.reason_codes)", evaluation)
        self.assertIn("return 'non_target'", evaluation)
        self.assertIn("evaluate_source_item_gates", evaluation)

    def test_rollback_keeps_rows_and_restores_prior_contract(self) -> None:
        lowered = self.down.lower()
        error = lowered.find("raise exception 'rollback_content_review_close_data_present'")
        drop = lowered.find("drop constraint ingest_review_decisions_type_ck")
        self.assertGreater(error, 0)
        self.assertLess(error, drop)
        self.assertNotIn("delete from machimoa_review.ingest_review_decisions", lowered)
        self.assertNotIn("delete from machimoa_review.processing_jobs", lowered)
        self.assertNotIn("delete from public.curations", lowered)
        self.assertNotIn("delete from machimoa_review.curation_candidates", lowered)
        self.assertNotIn("grant execute", lowered)
        self.assertEqual(_private_grant_signatures(self.down), set())
        self.assertIn(
            "check (review_type in ('region', 'relevance'))",
            self.down,
        )
        restored = self.down.split(
            "create or replace function machimoa_review.apply_ingest_review_decision"
        )[1].split("create or replace function")[0]
        self.assertIn("v_type not in ('region', 'relevance')", restored)
        self.assertNotIn("when 'content' then", restored)
        self.assertNotIn("content_review_not_open", restored)
        self.assertNotIn("curation_candidate_exists", restored)
        restored_eval = self.down.split(
            "create or replace function machimoa_review.apply_source_item_evaluation"
        )[1]
        self.assertNotIn("v_closed", restored_eval)
        self.assertIn("evaluate_source_item_gates", restored_eval)


if __name__ == "__main__":
    unittest.main()
