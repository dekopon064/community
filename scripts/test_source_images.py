"""Synthetic metadata cases only; no network, AI or operational DB."""
import unittest
from ingest.source_images import first_content_image, source_image_url
from ingest.connectors.youthcenter_content import YouthcenterContentConnector, content_revision_hash
from ingest.connectors.seoul_reservation import normalize_seoul_item
from test_seoul_reservation import row


class SourceImageTests(unittest.TestCase):
    def test_external_urls_and_rejected_values(self):
        for value in ("https://images.example.org/poster.jpg", "https://images.example.org:443/get?id=2&size=300", " HTTPS://IMAGES.EXAMPLE.ORG/a.png "):
            self.assertEqual(source_image_url(value), value.strip())
        for value in (None, 3, "", "data:image/png;base64,SECRET", "http://images.example.org/a.jpg", "//images.example.org/a.jpg", "https://127.0.0.1/a", "https://user:secret@images.example.org/a", "https://images.example.org:8443/a", "https://images.local/a", "https://images.example.org/a.svg", "https://images.example.org/a#secret", "https://images.example.org/\nsecret", "https://images.example.org/a\n", "https://images.example.org/%0a", "https://images.example.org/" + "x" * 2048):
            with self.subTest(value=type(value).__name__):
                self.assertIsNone(source_image_url(value))

    def test_only_existing_content_image_not_scripts_tracking_or_data(self):
        html = '<script>document.write("<img src=\"https://images.example.org/script.png\">")</script><img width="1" src="https://images.example.org/tracking.gif"><img src="data:image/png;base64,SECRET"><img src="/assets/poster.png"><img src="https://images.example.org/second.jpg">'
        self.assertEqual(first_content_image(html, "https://www.youthcenter.go.kr/"), "https://www.youthcenter.go.kr/assets/poster.png")
        self.assertIsNone(first_content_image('<iframe><img src="https://images.example.org/hidden.png"></iframe>', "https://www.youthcenter.go.kr/"))

    def test_content_normalization_drops_blobs_keeps_one_url_and_revision(self):
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        item = {"bbsSn": "48", "pstSn": "image-test", "pstTtl": "가상 제목", "pstSeNm": "기타", "pstUrlAddr": "https://www.youthcenter.go.kr/content", "pstWholCn": '<p>원문 설명입니다. 충분히 긴 본문을 보존합니다.</p><img src="https://images.example.org/first.png">', "atchFile": "data:image/png;base64,SECRET"}
        record = connector.to_observation(item, permission_status="testing_only", enabled=False)
        self.assertEqual(record.normalized_payload["source_image_url"], "https://images.example.org/first.png")
        self.assertNotIn("SECRET", str(record.to_rpc_item()))
        self.assertNotIn("<img", str(record.normalized_payload))
        changed = connector.to_observation({**item, "pstWholCn": item["pstWholCn"].replace("first", "second")}, permission_status="testing_only", enabled=False)
        self.assertNotEqual(record.revision_hash, changed.revision_hash)
        plain = record.normalized_payload["plain_text"]
        self.assertEqual(content_revision_hash(item, plain_text=plain, source_url=item["pstUrlAddr"]), content_revision_hash(item, plain_text=plain, source_url=item["pstUrlAddr"], image_url=None))
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_seoul_explicit_image_url_and_absence(self):
        with_image = normalize_seoul_item(row(IMGURL="https://images.example.org/seoul.jpg"))
        self.assertEqual(with_image.normalized_payload["source_image_url"], "https://images.example.org/seoul.jpg")
        self.assertIsNone(normalize_seoul_item(row()).normalized_payload["source_image_url"])
        self.assertIsNone(normalize_seoul_item(row(IMGURL="data:image/png;base64,SECRET")).normalized_payload["source_image_url"])


if __name__ == "__main__":
    unittest.main()
