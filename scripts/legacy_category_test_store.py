"""Seed the policy category for pre-category tests focused on older contracts.

New category/period tests use MemoryIngestStore directly. This fixture keeps the
older suites' explicit application-deadline scenarios independent of taxonomy.
"""

from __future__ import annotations

from ingest.store import MemoryIngestStore


class LegacyCategoryFixtureStore(MemoryIngestStore):
    def _required_period_reasons(self, item):
        self.user_categories.setdefault((item.id, item.revision_hash), "policy")
        return super()._required_period_reasons(item)

    def _period_facts_ready(self, item, revision_hash):
        self.user_categories.setdefault((item.id, revision_hash), "policy")
        return super()._period_facts_ready(item, revision_hash)
