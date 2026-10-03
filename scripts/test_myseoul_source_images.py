"""Synthetic body image cases only; no network, DB, download or provider."""
import hashlib
import json
import unittest

from ingest.connectors.myseoul_program import normalize_detail
from ingest.myseoul_db import myseoul_rpc_item
from test_myseoul_program import detail, url, NOW


class MyImageTests(unittest.TestCase):
    def record(self, images="", outside=""):
        return normalize_detail(detail(extra=images, outside=outside), url())

    def test_body_scope_relative_validation_and_selection(self):
        images = ('<img src="/logo.png" alt="센터 로고">'
                  '<img src="/poster.jpg" alt="프로그램 포스터">')
        record = self.record(images, '<img src="https://other.example.org/banner.png">')
        self.assertEqual(record.normalized_payload["source_image_url"],
                         "https://global.seoul.go.kr/poster.jpg")
        self.assertEqual(record.normalized_payload["source_image_selection"], "body_poster")
        self.assertEqual(myseoul_rpc_item(record, now=NOW)["normalized_payload"]["source_image_url"],
                         record.normalized_payload["source_image_url"])

    def test_invalid_hidden_logo_tracker_and_absent_do_not_fail_ingest(self):
        for image in ["", '<img src="http://global.seoul.go.kr/a.jpg">',
                      '<img src="https://127.0.0.1/a.jpg">', '<img src="/a.svg">',
                      '<img src="data:image/png;base64,ignored">',
                      '<img src="/a.jpg?token=ignored">', '<img src="/banner.jpg">',
                      '<img src="https://global.seoul.go.kr/a\n.jpg">',
                      '<img src="/a.jpg" width="1">',
                      '<div hidden><img src="/a.jpg"></div>',
                      '<template><img src="/a.jpg"></template>',
                      '<div style="display: none"><img src="/a.jpg"></div>']:
            with self.subTest(image=image):
                record = self.record(image)
                self.assertIsNone(record.normalized_payload["source_image_url"])
                self.assertEqual(record.revision_hash, self.record().revision_hash)
                self.assertEqual(record.normalized_payload["description"], self.record().normalized_payload["description"])

    def test_multiple_ambiguous_images_and_duplicate_urls(self):
        self.assertIsNone(self.record('<img src="/a.jpg"><img src="/b.jpg">').normalized_payload["source_image_url"])
        self.assertIsNone(self.record('<img src="/a.jpg" alt="포스터"><img src="/b.jpg" alt="포스터">').normalized_payload["source_image_url"])
        self.assertEqual(self.record('<img src="/a.jpg"><img src="/a.jpg">').normalized_payload["source_image_url"],
                         "https://global.seoul.go.kr/a.jpg")

    def test_add_change_remove_revision_and_unchanged_facts(self):
        none, first, second = self.record(), self.record('<img src="/a.jpg">'), self.record('<img src="/b.jpg">')
        self.assertNotEqual(none.revision_hash, first.revision_hash)
        self.assertNotEqual(first.revision_hash, second.revision_hash)
        self.assertEqual(self.record().revision_hash, none.revision_hash)
        self.assertEqual(first.revision_hash, self.record('<img src="https://global.seoul.go.kr/a.jpg">').revision_hash)
        fields = {k: v for k, v in none.normalized_payload.items() if k not in
                  {"parser_version", "revision_contract", "body_has_images", "attachment_links_present",
                   "source_image_url", "source_image_selection", "source_image_contract"}}
        original_hash = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(none.revision_hash, original_hash)
        old_facts, new_facts = (myseoul_rpc_item(r, now=NOW)["myseoul_facts"] for r in (none, first))
        self.assertEqual(old_facts.pop("source_revision"), none.revision_hash)
        self.assertEqual(new_facts.pop("source_revision"), first.revision_hash)
        self.assertEqual(old_facts, new_facts)


if __name__ == "__main__":
    unittest.main()
