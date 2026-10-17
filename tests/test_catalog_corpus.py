import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lavochkin_pipeline.catalog.import_corpus import load_corpus


class CorpusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "documents.jsonl"

    def write_rows(self, *rows):
        self.path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_valid_record_and_file_digest(self):
        self.write_rows({
            "ntrs_id": 123,
            "title": "Example",
            "text": "Document text",
            "has_nonempty_text": True,
        })
        records, digest = load_corpus(self.path)
        self.assertEqual(len(records), 1)
        ident, row, record_digest = records[0]
        self.assertEqual(ident, "123")
        self.assertEqual(row["text"], "Document text")
        self.assertNotIn("_catalog_import", row)
        canonical = json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(
            record_digest,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            digest, hashlib.sha256(self.path.read_bytes()).hexdigest()
        )

    def test_duplicate_ids_after_normalization(self):
        self.write_rows({"ntrs_id": 123}, {"ntrs_id": " 123 "})
        with self.assertRaisesRegex(ValueError, "Line 2:.*duplicate"):
            load_corpus(self.path)

    def test_boolean_id_rejected(self):
        self.write_rows({"ntrs_id": True})
        with self.assertRaisesRegex(ValueError, "ntrs_id must"):
            load_corpus(self.path)

    def test_nested_nuls_and_original_line_preserved(self):
        original = {
            "ntrs_id": "123",
            "text": "a\x00b",
            "metadata": {"items": ["c\x00d"]},
        }
        self.write_rows(original)
        original_bytes = self.path.read_bytes()
        records, _ = load_corpus(self.path)
        _, row, record_digest = records[0]
        self.assertEqual(row["text"], "a\ufffdb")
        self.assertEqual(row["metadata"]["items"], ["c\ufffdd"])
        provenance = row["_catalog_import"]
        self.assertEqual(provenance["normalization"], "NUL_to_U+FFFD_v1")
        self.assertEqual(
            base64.b64decode(provenance["original_json_line_utf8_base64"]),
            original_bytes,
        )
        canonical = json.dumps(
            original, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(record_digest, expected)
        self.assertEqual(provenance["original_canonical_sha256"], expected)

    def test_nul_in_key_rejected(self):
        self.write_rows({"ntrs_id": "123", "bad\x00key": "value"})
        with self.assertRaisesRegex(ValueError, "NUL in JSON key"):
            load_corpus(self.path)

    def test_reserved_key_rejected_when_normalizing(self):
        self.write_rows({
            "ntrs_id": "123",
            "text": "a\x00b",
            "_catalog_import": {},
        })
        with self.assertRaisesRegex(ValueError, "Reserved key"):
            load_corpus(self.path)

    def test_text_flag_must_match_text(self):
        for text, declared in [("content", False), ("   ", True), ("x", 1)]:
            with self.subTest(text=text, declared=declared):
                self.write_rows({
                    "ntrs_id": "123",
                    "text": text,
                    "has_nonempty_text": declared,
                })
                with self.assertRaisesRegex(ValueError, "disagrees with text"):
                    load_corpus(self.path)

    def test_empty_corpus_rejected(self):
        self.path.write_text("\n  \n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Corpus is empty"):
            load_corpus(self.path)

    def test_manifest_checksum(self):
        self.write_rows({"ntrs_id": "123"})
        manifest = self.directory / "manifest.json"
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        manifest.write_text(
            json.dumps({"output_documents_sha256": digest}),
            encoding="utf-8",
        )
        load_corpus(self.path)
        manifest.write_text(
            json.dumps({"output_documents_sha256": "0" * 64}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_corpus(self.path)


if __name__ == "__main__":
    unittest.main()
