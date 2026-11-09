"""Generate Markdown and JSON reports from a stored Douyin snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIRECTORY.parent
SOURCE_DIRECTORY = PROJECT_ROOT / "src"
if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))

from douyin_data_ops.reporting import ReportGenerator


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为一个抖音作品快照生成 Markdown 和 JSON 复盘报告"
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="项目根目录")
    parser.add_argument("--account", default="main", help="账号标识")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--latest", action="store_true", help="使用最新作品快照")
    target.add_argument("--snapshot", help="指定 snapshot_id")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = parse_arguments()
    snapshot_id = arguments.snapshot
    generator = ReportGenerator(
        Path(arguments.root).resolve(),
        account_label=arguments.account,
        snapshot_id=snapshot_id,
    )
    try:
        result = generator.generate()
    finally:
        generator.close()
    print(
        json.dumps(
            {
                "snapshot_id": result.payload["snapshot"]["snapshot_id"],
                "markdown_path": str(result.markdown_path),
                "json_path": str(result.json_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

