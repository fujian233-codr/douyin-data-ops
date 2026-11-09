import shutil
import tempfile
import unittest
from pathlib import Path

from douyin_data_ops.importer import DataImporter
from douyin_data_ops.reporting import ReportGenerator


FIXTURES = Path(__file__).parent / "fixtures"


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(Path(__file__).parents[1] / "config", self.root / "config")
        inbox = self.root / "data" / "inbox"
        inbox.mkdir(parents=True)
        self.reports = self.root / "reports"
        self.reports.mkdir()
        self.importer = DataImporter(self.root, account_label="main")
        self.summary = self.importer.import_file(FIXTURES / "works_basic.csv")
        self.generator: ReportGenerator | None = None

    def tearDown(self):
        if self.generator is not None:
            self.generator.close()
        self.importer.close()
        self.temporary.cleanup()

    def test_report_marks_small_base_missing_field_and_topic(self):
        self.generator = ReportGenerator(
            self.root,
            account_label="main",
            snapshot_id=self.summary.snapshot_id,
        )
        result = self.generator.generate()

        self.assertTrue(result.markdown_path.exists())
        self.assertTrue(result.json_path.exists())
        payload = result.payload
        self.assertEqual(payload["account_label"], "main")
        self.assertEqual(payload["works"]["count"], 3)
        self.assertGreaterEqual(payload["coverage"]["missing_core_fields"], 1)
        small = [row for row in payload["works"]["recent"] if row["small_base"]]
        self.assertEqual(small[0]["video_id"], "7704301008546177728")

        topics = {row["topic"]: row for row in payload["topics"]}
        self.assertIn("赛事科普", topics)
        self.assertIn("风光氛围", topics)

        markdown = result.markdown_path.read_text(encoding="utf-8")
        self.assertIn("小基数", markdown)
        self.assertIn("5秒完播率缺失", markdown)
        self.assertIn("开头钩子", markdown)

    def test_account_overview_uses_all_metric_rows_not_only_recent_twenty(self):
        for index in range(21):
            video_id = f"7700000000000000{index:03d}"
            self.importer.database.upsert_work(
                account_label="main",
                video_id=video_id,
                title=f"最近低播放作品{index}",
                publish_time=f"2026-11-{index + 1:02d}T21:30:00",
                duration_seconds=60,
                status="已发布",
                content_kind="视频",
            )
            self.importer.database.insert_work_metric(
                {
                    "snapshot_id": self.summary.snapshot_id,
                    "account_label": "main",
                    "video_id": video_id,
                    "play_count": 100,
                    "exposure_count": None,
                    "like_count": 10,
                    "comment_count": 1,
                    "share_count": 1,
                    "collect_count": 1,
                    "follower_gain": 1,
                    "homepage_visits": None,
                    "five_second_completion_rate": None,
                    "completion_rate": 0.1,
                    "two_second_bounce_rate": 0.3,
                    "cover_click_rate": None,
                    "average_watch_duration_seconds": None,
                    "raw_json": "{}",
                }
            )

        generator = ReportGenerator(
            self.root,
            account_label="main",
            snapshot_id=self.summary.snapshot_id,
        )
        try:
            result = generator.generate()
        finally:
            generator.close()

        works = result.payload["works"]
        self.assertEqual(works["total_work_count"], 24)
        self.assertEqual(works["count"], 24)
        self.assertEqual(works["recent"], works["recent"][:20])
        self.assertLessEqual(len(works["recent"]), 20)


if __name__ == "__main__":
    unittest.main()

