"""Static contract for the deadline RPC conflict-target repair.

This does not execute PostgreSQL or prove PL/pgSQL runtime behavior.
"""

from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "supabase/migrations/20260926000000_ingest_application_deadline_facts.sql"
UP = ROOT / "supabase/migrations/20260928000001_ingest_application_deadline_rpc_conflict.sql"
DOWN = ROOT / "supabase/rollback/20260928000001_ingest_application_deadline_rpc_conflict_down.sql"
FUNCTION = "machimoa_review.resolve_source_item_application_deadline"
OLD_CONFLICT = "on conflict (source_item_id, revision_hash) do update"
NEW_CONFLICT = "on conflict on constraint source_item_application_deadlines_pk do update"


def function_body(sql: str) -> str:
    match = re.search(
        rf"create (?:or replace )?function {re.escape(FUNCTION)}\([\s\S]*?\$function\$;",
        sql,
    )
    if match is None:
        raise AssertionError(f"{FUNCTION} body not found")
    return match.group().replace("create or replace function", "create function", 1)


class DeadlineRpcConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = BASE.read_text(encoding="utf-8")
        cls.up = UP.read_text(encoding="utf-8")
        cls.down = DOWN.read_text(encoding="utf-8")

    def test_named_conflict_constraint_exists(self) -> None:
        self.assertIn(
            "constraint source_item_application_deadlines_pk\n    primary key (source_item_id, revision_hash)",
            self.base,
        )

    def test_repair_changes_only_conflict_target(self) -> None:
        before = function_body(self.base)
        after = function_body(self.up)
        self.assertEqual(before.count(OLD_CONFLICT), 1)
        self.assertEqual(after, before.replace(OLD_CONFLICT, NEW_CONFLICT))
        self.assertNotIn(OLD_CONFLICT, after)
        self.assertIn("'application_deadline_unknown'", after)
        self.assertIn("machimoa_review.apply_source_item_evaluation(", after)

    def test_rollback_restores_previous_function_without_deleting_data(self) -> None:
        self.assertEqual(function_body(self.down), function_body(self.base))
        self.assertNotRegex(self.down.lower(), r"\b(delete|truncate|drop table)\b")

    def test_signature_owner_and_permissions_are_not_changed(self) -> None:
        for sql in (self.up, self.down):
            self.assertRegex(sql, rf"create or replace function {re.escape(FUNCTION)}\(")
            self.assertNotRegex(sql.lower(), r"\b(grant|revoke|alter function)\b")


if __name__ == "__main__":
    unittest.main()
