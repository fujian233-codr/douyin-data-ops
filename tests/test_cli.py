import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(PROJECT_ROOT / "config", self.root / "config")
        self.inbox = self.root / "data" / "inbox"
        self.inbox.mkdir(parents=True)
        shutil.copy2(FIXTURES / "works_basic.csv", self.inbox / "works.csv")

    def tearDown(self):
        self.temporary.cleanup()

    def run_command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / arguments[0]), *arguments[1:]],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_import_and_report_commands_execute_end_to_end(self):
        imported = self.run_command(
            "import_data.py",
            "--inbox",
            str(self.inbox),
            "--account",
            "main",
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        summaries = json.loads(imported.stdout)
        self.assertTrue(summaries[0]["imported"])
        self.assertEqual(summaries[0]["row_count"], 3)

        reported = self.run_command(
            "generate_report.py",
            "--root",
            str(self.root),
            "--account",
            "main",
            "--latest",
        )
        self.assertEqual(reported.returncode, 0, reported.stderr)
        result = json.loads(reported.stdout)
        self.assertTrue(Path(result["markdown_path"]).exists())
        self.assertTrue(Path(result["json_path"]).exists())

    def test_help_commands_are_available(self):
        for script in ("import_data.py", "generate_report.py"):
            completed = self.run_command(script, "--help")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("usage:", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()

