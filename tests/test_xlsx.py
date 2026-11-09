import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from douyin_data_ops.importer import DataImporter
from douyin_data_ops.analyzer import WorkAnalyzer
from douyin_data_ops.store import Database
from douyin_data_ops.xlsx import parse_daily_rows, read_sheet_rows


def build_xlsx(header: list[str], rows: list[list[str]]) -> bytes:
    """Minimal hand-rolled workbook: shared strings + one sheet."""

    strings: list[str] = []

    def shared(value: str) -> int:
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    def cell(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="s"><v>{shared(value)}</v></c>'

    letters = [chr(ord("A") + index) for index in range(len(header))]
    sheet_rows = ['<row r="1">' + "".join(cell(f"{col}1", h) for col, h in zip(letters, header)) + "</row>"]
    for number, row in enumerate(rows, start=2):
        sheet_rows.append(
            "<row r=\"{n}\">".format(n=number)
            + "".join(cell(f"{col}{number}", value) for col, value in zip(letters, row))
            + "</row>"
        )
    shared_xml = (
        '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


VIDEO_HEADER = ["日期", "投稿量", "总播放量", "总点赞量", "总分享量", "总评论量", "5秒完播率", "2秒跳出率", "封面点击率", "平均播放时长"]
FAN_HEADER = ["日期", "总粉丝量", "粉丝净增", "吸粉量", "脱粉量", "回访粉丝量"]


class XlsxReaderTests(unittest.TestCase):
    def test_reads_headers_and_rows(self):
        descriptor, name = tempfile.mkstemp(suffix=".xlsx")
        os.close(descriptor)
        target = Path(name)
        try:
            target.write_bytes(
                build_xlsx(
                    VIDEO_HEADER,
                    [["2026-10-10", "0", "54", "0", "0", "0", "45.28%", "43.40%", "38.60%", "9.21s"]],
                )
            )
            rows = read_sheet_rows(target)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["日期"], "2026-10-10")
            self.assertEqual(rows[0]["平均播放时长"], "9.21s")
        finally:
            target.unlink(missing_ok=True)

    def test_rejects_non_xlsx(self):
        descriptor, name = tempfile.mkstemp(suffix=".xlsx")
        os.close(descriptor)
        target = Path(name)
        try:
            target.write_bytes(b"not a zip")
            with self.assertRaises(ValueError):
                read_sheet_rows(target)
        finally:
            target.unlink(missing_ok=True)


class DailyParseTests(unittest.TestCase):
    def test_video_rows_parse_rates_and_seconds(self):
        _, parsed, issues = parse_daily_rows(
            [dict(zip(VIDEO_HEADER, ["2026-10-10", "0", "54", "0", "0", "0", "45.28%", "43.40%", "38.60%", "9.21s"]))]
        )
        self.assertEqual(issues, [])
        self.assertEqual(parsed[0]["play_count"], 54)
        self.assertAlmostEqual(parsed[0]["five_second_completion_rate"], 0.4528)
        self.assertAlmostEqual(parsed[0]["two_second_bounce_rate"], 0.434)
        self.assertAlmostEqual(parsed[0]["average_watch_duration_seconds"], 9.21)

    def test_fan_rows_keep_negative_net(self):
        _, parsed, _ = parse_daily_rows(
            [dict(zip(FAN_HEADER, ["2026-10-12", "297", "-1", "0", "1", "0"]))]
        )
        self.assertEqual(parsed[0]["follower_net"], -1)
        self.assertEqual(parsed[0]["follower_loss"], 1)
        self.assertEqual(parsed[0]["total_fans"], 297)

    def test_invalid_date_is_rejected(self):
        _, parsed, issues = parse_daily_rows(
            [dict(zip(FAN_HEADER, ["10/12", "297", "-1", "0", "1", "0"]))]
        )
        self.assertEqual(parsed, [])
        self.assertEqual(issues[0]["issue_type"], "invalid_date")

    def test_unknown_layout_is_rejected(self):
        kind, _, _ = parse_daily_rows([{"foo": "bar"}])
        self.assertEqual(kind, "")


class DailyImportTests(unittest.TestCase):
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

    def _write(self, name: str, header: list[str], rows: list[list[str]]) -> Path:
        target = self.inbox / name
        target.write_bytes(build_xlsx(header, rows))
        return target

    def test_import_video_and_fan_daily_files(self):
        video = self._write(
            "daily-video-20261109.xlsx",
            VIDEO_HEADER,
            [
                ["2026-10-10", "0", "54", "0", "0", "0", "45.28%", "43.40%", "38.60%", "9.21s"],
                ["2026-10-11", "1", "128000", "9500", "410", "320", "52.10%", "35.20%", "5.20%", "14.30s"],
            ],
        )
        fan = self._write(
            "daily-fans-20261109.xlsx",
            FAN_HEADER,
            [["2026-10-10", "298", "1", "1", "0", "3"], ["2026-10-11", "299", "1", "2", "1", "4"]],
        )
        video_summary = self.importer.import_file(video)
        fan_summary = self.importer.import_file(fan)

        self.assertTrue(video_summary.imported)
        self.assertEqual(video_summary.kind, "daily_metrics")
        self.assertEqual(video_summary.row_count, 2)
        self.assertEqual(video_summary.field_coverage["daily_kind"], "video")
        self.assertTrue(fan_summary.imported)
        self.assertEqual(fan_summary.field_coverage["daily_kind"], "fan")

        merged = self.importer.database.daily_metrics_rows("main")
        self.assertEqual(len(merged), 2)
        by_date = {row["stat_date"]: row for row in merged}
        self.assertEqual(by_date["2026-10-11"]["play_count"], 128000)
        self.assertEqual(by_date["2026-10-11"]["follower_net"], 1)
        self.assertAlmostEqual(
            by_date["2026-10-11"]["five_second_completion_rate"], 0.521
        )

    def test_duplicate_daily_file_is_skipped(self):
        target = self._write(
            "daily-video-20261109.xlsx",
            VIDEO_HEADER,
            [["2026-10-10", "0", "54", "0", "0", "0", "45.28%", "43.40%", "38.60%", "9.21s"]],
        )
        self.assertTrue(self.importer.import_file(target).imported)
        second = self.importer.import_file(target)
        self.assertFalse(second.imported)
        self.assertEqual(second.skip_reason, "duplicate_sha256")

    def test_directory_mixes_csv_json_and_xlsx(self):
        self._write(
            "daily-video-20261109.xlsx",
            VIDEO_HEADER,
            [["2026-10-10", "0", "54", "0", "0", "0", "45.28%", "43.40%", "38.60%", "9.21s"]],
        )
        shutil.copy2(
            Path(__file__).parent / "fixtures" / "works_basic.csv",
            self.inbox / "works.csv",
        )
        summaries = self.importer.import_directory(self.inbox)
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(summary.imported for summary in summaries))


class MigrationTests(unittest.TestCase):
    def test_old_snapshots_check_is_migrated(self):
        root = Path(tempfile.mkdtemp())
        try:
            database = Database(root / "old.db")
            with database.transaction() as connection:
                connection.executescript(
                    """
                    CREATE TABLE snapshots (
                      snapshot_id TEXT PRIMARY KEY,
                      account_label TEXT NOT NULL,
                      source_tool TEXT NOT NULL,
                      kind TEXT NOT NULL CHECK(kind IN ('works', 'fan_profiles')),
                      collected_at TEXT NOT NULL,
                      source_file TEXT NOT NULL,
                      sha256 TEXT NOT NULL UNIQUE,
                      status TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    );
                    INSERT INTO snapshots VALUES
                      ('works-old', 'main', 'test', 'works', '2026-01-01T00:00:00', 'a.csv', 'abc', 'complete', '2026-01-01T00:00:00');
                    """
                )
            database.create_schema()
            kept = database.get_snapshot("works-old")
            self.assertIsNotNone(kept)
            database.create_snapshot(
                account_label="main",
                source_tool="test",
                collected_at="2026-01-02T00:00:00",
                source_file="b.xlsx",
                sha256="def",
                kind="daily_metrics",
            )
            self.assertEqual(
                database.connection.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE kind='daily_metrics'"
                ).fetchone()[0],
                1,
            )
            database.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(Path(__file__).parents[1] / "config", self.root / "config")
        self.inbox = self.root / "data" / "inbox"
        self.inbox.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_comparison_between_two_works_snapshots(self):
        first = self.inbox / "works-20261101-0900.csv"
        first.write_text(
            "作品id,作品标题,发布时间,播放量,点赞量\n"
            "1111111111111111111,作品A,2026-10-01 10:00:00,1000,50\n"
            "2222222222222222222,作品B,2026-10-02 10:00:00,2000,80\n",
            encoding="utf-8",
        )
        second = self.inbox / "works-20261109-0900.csv"
        second.write_text(
            "作品id,作品标题,发布时间,播放量,点赞量\n"
            "1111111111111111111,作品A,2026-10-01 10:00:00,1500,60\n"
            "2222222222222222222,作品B,2026-10-02 10:00:00,1200,70\n"
            "3333333333333333333,作品C,2026-11-08 10:00:00,900,40\n",
            encoding="utf-8",
        )
        importer = DataImporter(self.root, account_label="main")
        importer.import_directory(self.inbox)
        latest = importer.database.latest_snapshot("main", "works")
        importer.close()

        database = Database(self.root / "data" / "douyin.db")
        try:
            analysis = WorkAnalyzer(database, self.root, str(latest["snapshot_id"])).build()
        finally:
            database.close()

        comparison = analysis["comparison"]
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["compared_work_count"], 2)
        self.assertEqual(len(comparison["new_works"]), 1)
        self.assertEqual(comparison["new_works"][0]["video_id"], "3333333333333333333")
        riser = comparison["risers"][0]
        self.assertEqual(riser["video_id"], "1111111111111111111")
        self.assertEqual(riser["delta"], 500)
        faller = comparison["fallers"][0]
        self.assertEqual(faller["video_id"], "2222222222222222222")
        self.assertEqual(faller["delta"], -800)
