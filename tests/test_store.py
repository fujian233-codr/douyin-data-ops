import tempfile
import unittest
from pathlib import Path

from douyin_data_ops.store import Database


class DatabaseTests(unittest.TestCase):
    def test_create_schema_and_detect_duplicate_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            with database:
                database.create_schema()
                tables = {
                    row[0]
                    for row in database.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("snapshots", tables)
                self.assertIn("works", tables)
                self.assertIn("work_metrics", tables)
                self.assertIn("fan_profiles", tables)
                self.assertIn("import_issues", tables)

                snapshot_id = database.create_snapshot(
                    account_label="main",
                    source_tool="DouyinDataReview",
                    collected_at="2026-11-07T21:30:00",
                    source_file="works.csv",
                    sha256="a" * 64,
                )
                self.assertTrue(database.snapshot_exists("a" * 64))
                with self.assertRaises(ValueError):
                    database.create_snapshot(
                        account_label="main",
                        source_tool="DouyinDataReview",
                        collected_at="2026-11-07T21:31:00",
                        source_file="works-copy.csv",
                        sha256="a" * 64,
                    )
                self.assertEqual(
                    database.latest_snapshot("main", "works")["snapshot_id"],
                    snapshot_id,
                )


if __name__ == "__main__":
    unittest.main()

