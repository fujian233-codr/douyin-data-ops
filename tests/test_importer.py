import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from douyin_data_ops.importer import DataImporter


FIXTURES = Path(__file__).parent / "fixtures"


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(Path(__file__).parents[1] / "config", self.root / "config")
        self.inbox = self.root / "data" / "inbox"
        self.inbox.mkdir(parents=True)
        self.importer = DataImporter(self.root, account_label="main")

    def tearDown(self):
        self.importer.close()
        self.temporary.cleanup()

    def test_import_works_csv_preserves_missing_values_and_records_issues(self):
        target = self.inbox / "works.csv"
        shutil.copy2(FIXTURES / "works_basic.csv", target)
        summary = self.importer.import_file(target)

        self.assertTrue(summary.imported)
        self.assertEqual(summary.kind, "works")
        self.assertEqual(summary.row_count, 3)
        self.assertEqual(summary.issue_count, 1)
        self.assertIn("five_second_completion_rate", summary.missing_fields)

        row = self.importer.database.connection.execute(
            """SELECT play_count, like_count, five_second_completion_rate,
                      completion_rate, two_second_bounce_rate,
                      average_watch_duration_seconds, video_id
               FROM work_metrics WHERE video_id=?""",
            ("7704505313186597775",),
        ).fetchone()
        self.assertEqual(row["play_count"], 1200)
        self.assertEqual(row["like_count"], 80)
        self.assertIsNone(row["five_second_completion_rate"])
        self.assertAlmostEqual(row["completion_rate"], 0.3684)
        self.assertAlmostEqual(row["two_second_bounce_rate"], 0.721)
        self.assertEqual(row["average_watch_duration_seconds"], 63)

        issues = self.importer.database.connection.execute(
            "SELECT field_name, issue_type FROM import_issues"
        ).fetchall()
        self.assertIn(
            {"field_name": "completion_rate", "issue_type": "invalid_rate"},
            [dict(row) for row in issues],
        )

    def test_import_same_file_twice_is_idempotent(self):
        target = self.inbox / "works.csv"
        shutil.copy2(FIXTURES / "works_english.csv", target)
        first = self.importer.import_file(target)
        second = self.importer.import_file(target)

        self.assertTrue(first.imported)
        self.assertFalse(second.imported)
        self.assertEqual(second.skip_reason, "duplicate_sha256")
        count = self.importer.database.connection.execute(
            "SELECT COUNT(*) AS n FROM snapshots"
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_import_fan_profiles(self):
        target = self.inbox / "fans.csv"
        shutil.copy2(FIXTURES / "fan_profiles.csv", target)
        summary = self.importer.import_file(target)

        self.assertTrue(summary.imported)
        self.assertEqual(summary.kind, "fan_profiles")
        self.assertEqual(summary.row_count, 3)
        row = self.importer.database.connection.execute(
            "SELECT value, ratio FROM fan_profiles WHERE dimension='性别' AND segment='男'"
        ).fetchone()
        self.assertEqual(row["value"], 1200)
        self.assertAlmostEqual(row["ratio"], 0.65)

    def test_unrecognized_csv_records_issue_without_import(self):
        target = self.inbox / "unknown.csv"
        target.write_text("foo\nbar\n", encoding="utf-8-sig")
        summary = self.importer.import_file(target)
        self.assertFalse(summary.imported)
        self.assertEqual(summary.skip_reason, "unrecognized_csv")


if __name__ == "__main__":
    unittest.main()

