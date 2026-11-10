import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
COLLECTOR_DIRECTORY = PROJECT_ROOT / "collector"
for entry in (str(COLLECTOR_DIRECTORY), str(PROJECT_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import api  # noqa: E402
from session import SessionError, build_session, cookie_header, load_session, save_session  # noqa: E402
from douyin_data_ops.importer import DataImporter  # noqa: E402


def sample_cookies() -> list[dict]:
    return [
        {"name": "sessionid", "value": "abc123", "domain": ".douyin.com", "path": "/"},
        {"name": "UIFID", "value": "uif-1", "domain": ".douyin.com", "path": "/"},
        {"name": "other", "value": "x", "domain": "example.com", "path": "/"},
    ]


def sample_session() -> dict:
    return build_session(
        cookies=sample_cookies(),
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Test",
        request_headers={
            "accept-language": "zh-CN,zh;q=0.9",
            "sec-ch-ua": '"Chromium";v="130"',
            "evil-header": "should-be-dropped",
        },
        uid="123",
        identity={"nickname": "测试号", "follower_count": 300},
    )


class SessionTests(unittest.TestCase):
    def test_build_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"
            session = sample_session()
            save_session(path, session)
            loaded = load_session(path)
            self.assertEqual(loaded["uid"], "123")
            self.assertEqual(len(loaded["cookies"]), 2)
            self.assertEqual(loaded["identity"]["nickname"], "测试号")

    def test_missing_login_cookie_rejected(self):
        cookies = [cookie for cookie in sample_cookies() if cookie["name"] != "sessionid"]
        with self.assertRaises(SessionError):
            build_session(
                cookies=cookies,
                user_agent="Mozilla/5.0 test",
                request_headers={},
            )

    def test_cookie_header_and_safe_headers(self):
        session = sample_session()
        self.assertIn("sessionid=abc123", cookie_header(session))
        self.assertIn("UIFID=uif-1", cookie_header(session))
        headers = api.safe_request_headers(session)
        self.assertIn("accept-language", headers)
        self.assertNotIn("evil-header", headers)


class EndpointBuilderTests(unittest.TestCase):
    def test_user_info_url(self):
        prepared = api.creator_request("user_info")
        self.assertEqual(prepared["method"], "GET")
        self.assertTrue(prepared["url"].startswith("https://creator.douyin.com/aweme/v1/creator/user/info/"))
        self.assertIn("aid=2906", prepared["url"])

    def test_work_list_params_pass_through(self):
        prepared = api.creator_request(
            "work_list", {"status": "0", "count": "20", "max_cursor": "123"}
        )
        self.assertIn("scene=star_atlas", prepared["url"])
        self.assertIn("max_cursor=123", prepared["url"])

    def test_dashboard_post_body(self):
        prepared = api.creator_request("dashboard", {"recent_days": "7"})
        self.assertEqual(prepared["method"], "POST")
        self.assertEqual(json.loads(prepared["body"]), {"recent_days": 7})

    def test_unknown_key_and_bad_params_rejected(self):
        self.assertEqual(api.creator_request("publish", {}), {})
        self.assertEqual(api.creator_request("user_info", {"hack": "1"}), {})
        self.assertEqual(api.creator_request("user_info", {"item_id": "x; DROP"}), {})


class DirectSnapshotImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(PROJECT_ROOT / "config", self.root / "config")
        self.inbox = self.root / "data" / "inbox"
        self.inbox.mkdir(parents=True)
        self.importer = DataImporter(self.root, account_label="main")

    def tearDown(self):
        self.importer.close()
        self.temporary.cleanup()

    def test_direct_source_snapshot_imports(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "mcp_snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        fixture["source"] = "douyin-direct"
        target = self.inbox / "direct-20261111-0900.json"
        target.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        summary = self.importer.import_file(target)

        self.assertTrue(summary.imported)
        self.assertEqual(summary.row_count, 3)
        snapshot = self.importer.database.connection.execute(
            "SELECT source_tool FROM snapshots WHERE snapshot_id=?",
            (summary.snapshot_id,),
        ).fetchone()
        self.assertEqual(snapshot["source_tool"], "douyin-direct")


if __name__ == "__main__":
    unittest.main()
