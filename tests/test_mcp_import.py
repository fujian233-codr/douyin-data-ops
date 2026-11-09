import json
import shutil
import tempfile
import unittest
from pathlib import Path

from douyin_data_ops.importer import DataImporter
from douyin_data_ops.mcp import build_snapshot_rows
from douyin_data_ops.analyzer import WorkAnalyzer
from douyin_data_ops.store import Database


FIXTURES = Path(__file__).parent / "fixtures"


class McpSnapshotTests(unittest.TestCase):
    def setUp(self):
        with (FIXTURES / "mcp_snapshot.json").open("r", encoding="utf-8") as handle:
            self.payload = json.load(handle)

    def test_parses_works_metrics_and_identity(self):
        rows = build_snapshot_rows(self.payload)
        works = {work["video_id"]: work for work in rows["works"]}
        self.assertEqual(len(works), 3)

        first = works["7459999999999999991"]
        self.assertEqual(first["title"], "F1 为什么禁止地面效应扩散器")
        self.assertEqual(first["duration_seconds"], 95)
        self.assertEqual(first["status"], "已发布")
        self.assertEqual(first["metrics"]["play_count"], 128000)
        self.assertEqual(first["metrics"]["collect_count"], 1200)
        self.assertEqual(first["metrics"]["follower_gain"], 180)
        self.assertAlmostEqual(first["metrics"]["two_second_bounce_rate"], 0.35)
        self.assertIsNone(first["metrics"]["five_second_completion_rate"])

    def test_private_work_metrics_are_hidden(self):
        rows = build_snapshot_rows(self.payload)
        works = {work["video_id"]: work for work in rows["works"]}
        private = works["7459999999999999993"]
        self.assertEqual(private["status"], "私密")
        self.assertIsNone(private["metrics"]["play_count"])

    def test_play_source_merges_profile_entries_and_filters_noise(self):
        rows = build_snapshot_rows(self.payload)
        works = {work["video_id"]: work for work in rows["works"]}
        sources = {
            item["name"]: item["ratio"]
            for item in works["7459999999999999991"]["enrichment"]["play_source"]
        }
        self.assertAlmostEqual(sources["个人主页"], 0.09)
        self.assertNotIn("tiny_source", sources)
        self.assertAlmostEqual(sources["推荐页"], 0.45)

    def test_fans_summary_becomes_profile_rows(self):
        rows = build_snapshot_rows(self.payload)
        dimensions = {row["dimension"] for row in rows["fan_rows"]}
        self.assertIn("性别分布", dimensions)
        self.assertIn("年龄分布", dimensions)
        male = next(row for row in rows["fan_rows"] if row["segment"] == "男性")
        self.assertAlmostEqual(male["ratio"], 0.86)


class McpImportTests(unittest.TestCase):
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

    def _copy_fixture(self, name: str = "mcp-20261109-2130.json") -> Path:
        target = self.inbox / name
        shutil.copy2(FIXTURES / "mcp_snapshot.json", target)
        return target

    def test_import_mcp_snapshot(self):
        summary = self.importer.import_file(self._copy_fixture())

        self.assertTrue(summary.imported)
        self.assertEqual(summary.kind, "works")
        self.assertEqual(summary.row_count, 3)
        self.assertEqual(summary.field_coverage["metric_work_count"], 2)
        self.assertEqual(summary.field_coverage["fan_profile_rows"], 4)
        self.assertIn("work_list", summary.field_coverage["query_keys"])

        snapshot = self.importer.database.connection.execute(
            "SELECT source_tool, kind FROM snapshots WHERE snapshot_id=?",
            (summary.snapshot_id,),
        ).fetchone()
        self.assertEqual(snapshot["source_tool"], "DouyinDataReview-MCP")
        self.assertEqual(snapshot["kind"], "works")

        fans = self.importer.database.connection.execute(
            "SELECT COUNT(*) AS n FROM fan_profiles WHERE snapshot_id=?",
            (summary.snapshot_id,),
        ).fetchone()["n"]
        self.assertEqual(fans, 4)

    def test_import_mcp_snapshot_twice_skips_duplicate(self):
        target = self._copy_fixture()
        first = self.importer.import_file(target)
        second = self.importer.import_file(target)

        self.assertTrue(first.imported)
        self.assertFalse(second.imported)
        self.assertEqual(second.skip_reason, "duplicate_sha256")

    def test_import_directory_accepts_json_and_csv_together(self):
        self._copy_fixture()
        shutil.copy2(FIXTURES / "works_basic.csv", self.inbox / "works.csv")
        summaries = self.importer.import_directory(self.inbox)

        self.assertEqual(len(summaries), 2)
        self.assertEqual(sum(1 for summary in summaries if summary.imported), 2)

    def test_non_mcp_json_is_rejected(self):
        target = self.inbox / "other.json"
        target.write_text('{"source": "other"}', encoding="utf-8")
        summary = self.importer.import_file(target)
        self.assertFalse(summary.imported)
        self.assertEqual(summary.skip_reason, "unrecognized_json")

    def test_analyzer_aggregates_play_sources(self):
        summary = self.importer.import_file(self._copy_fixture())
        database = Database(self.root / "data" / "douyin.db")
        try:
            analysis = WorkAnalyzer(database, self.root, summary.snapshot_id).build()
        finally:
            database.close()

        self.assertTrue(analysis["play_sources"]["available"])
        aggregate = {
            item["name"]: item["ratio"]
            for item in analysis["play_sources"]["aggregate"]
        }
        weighted_recommend = (0.45 * 128000 + 0.40 * 22000) / 150000
        self.assertAlmostEqual(aggregate["推荐页"], round(weighted_recommend, 6))
        conclusions = analysis["diagnostics"]["conclusions"]
        self.assertTrue(
            any(item["type"] == "traffic_recommend_weak" for item in conclusions)
        )
