import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lavochkin_pipeline.catalog.import_topics import load_inputs


class TopicTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

        self.topics = [
            {
                "k": 2,
                "representative_seed": 7,
                "topic": 0,
                "mean_matched_cosine": 0.9,
                "mean_relative_weight": 0.5,
                "leading_record_count": 1,
                "top_terms": "venus | atmosphere",
            },
            {
                "k": 2,
                "representative_seed": 7,
                "topic": 1,
                "mean_matched_cosine": 0.8,
                "mean_relative_weight": 0.5,
                "leading_record_count": 1,
                "top_terms": "moon | surface",
            },
        ]
        self.profiles = [
            {"k": 2, "representative_seed": 7,
             "ntrs_id": "101", "topic": 0, "relative_weight": 0.75},
            {"k": 2, "representative_seed": 7,
             "ntrs_id": "101", "topic": 1, "relative_weight": 0.25},
            {"k": 2, "representative_seed": 7,
             "ntrs_id": "102", "topic": 0, "relative_weight": 0.25},
            {"k": 2, "representative_seed": 7,
             "ntrs_id": "102", "topic": 1, "relative_weight": 0.75},
        ]

    def write_inputs(self):
        datasets = [
            ("representative_topics.csv", self.topics),
            ("representative_record_profiles.csv", self.profiles),
        ]
        for filename, rows in datasets:
            with (self.directory / filename).open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

    def load(self):
        self.write_inputs()
        return load_inputs(self.directory, 2)

    def assert_invalid(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.load()

    def test_valid_inputs_and_fingerprint(self):
        topics, profiles, seed, hashes, fingerprint, key = self.load()
        self.assertEqual(set(topics), {0, 1})
        self.assertEqual(profiles, {
            "101": {0: 0.75, 1: 0.25},
            "102": {0: 0.25, 1: 0.75},
        })
        self.assertEqual(seed, 7)
        expected_hashes = {
            name: hashlib.sha256(
                (self.directory / name).read_bytes()
            ).hexdigest()
            for name in (
                "representative_topics.csv",
                "representative_record_profiles.csv",
            )
        }
        self.assertEqual(hashes, expected_hashes)
        expected_fingerprint = hashlib.sha256(
            json.dumps(expected_hashes, sort_keys=True).encode()
        ).hexdigest()
        self.assertEqual(fingerprint, expected_fingerprint)
        self.assertEqual(key, f"nmf-k2-seed7-{expected_fingerprint}")

    def test_invalid_weights(self):
        for value in (-0.1, 1.1, "nan", "inf", "-inf"):
            with self.subTest(weight=value):
                self.profiles[0]["relative_weight"] = value
                self.assert_invalid("Invalid profile cell")

    def test_duplicate_profile_cell(self):
        self.profiles.append(dict(self.profiles[0]))
        self.assert_invalid("Duplicate profile cell")

    def test_incomplete_profile(self):
        self.profiles.pop()
        self.assert_invalid("Incomplete or non-normalized profile")

    def test_non_normalized_profile(self):
        self.profiles[0]["relative_weight"] = 0.5
        self.assert_invalid("Incomplete or non-normalized profile")

    def test_duplicate_topic(self):
        self.topics.append(dict(self.topics[0]))
        self.assert_invalid("Duplicate or invalid topic number")

    def test_incomplete_topic_list(self):
        self.topics.pop()
        self.assert_invalid("Incomplete topic list")

    def test_mixed_seeds(self):
        self.profiles[0]["representative_seed"] = 8
        self.assert_invalid("Expected exactly one representative seed")

    def test_mean_disagrees_with_profiles(self):
        self.topics[0]["mean_relative_weight"] = 0.6
        self.assert_invalid("Topic statistics disagree with profiles")

    def test_leading_count_disagrees_with_profiles(self):
        self.topics[0]["leading_record_count"] = 2
        self.assert_invalid("Topic statistics disagree with profiles")

    def test_invalid_topic_statistics(self):
        for field, value in (
            ("mean_matched_cosine", "nan"),
            ("mean_matched_cosine", 1.1),
            ("mean_relative_weight", -0.1),
            ("leading_record_count", -1),
        ):
            with self.subTest(field=field, value=value):
                original = self.topics[0][field]
                try:
                    self.topics[0][field] = value
                    self.assert_invalid("Invalid topic statistics")
                finally:
                    self.topics[0][field] = original

    def test_missing_requested_k(self):
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "No data for requested k"):
            load_inputs(self.directory, 3)


if __name__ == "__main__":
    unittest.main()
