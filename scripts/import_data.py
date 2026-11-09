"""Import DouyinDataReview CSV exports into the local SQLite database."""

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

from douyin_data_ops.importer import DataImporter, ImportSummary


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="导入 DouyinDataReview 导出的作品数据或粉丝画像 CSV"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="项目根目录；缺省时从 --inbox 反推，或使用本脚本所在项目",
    )
    parser.add_argument(
        "--inbox",
        default=None,
        help="CSV 输入目录，默认 <root>/data/inbox",
    )
    parser.add_argument("--account", default="main", help="账号标识，默认 main")
    return parser.parse_args()


def resolve_root(arguments: argparse.Namespace) -> Path:
    if arguments.root:
        return Path(arguments.root).resolve()
    if arguments.inbox:
        inbox = Path(arguments.inbox).resolve()
        if inbox.parent.name == "data":
            return inbox.parent.parent
    return PROJECT_ROOT


def summary_to_dict(summary: ImportSummary) -> dict[str, object]:
    return {
        "source_file": summary.source_file,
        "imported": summary.imported,
        "kind": summary.kind,
        "snapshot_id": summary.snapshot_id,
        "row_count": summary.row_count,
        "issue_count": summary.issue_count,
        "field_coverage": summary.field_coverage,
        "missing_fields": summary.missing_fields,
        "skip_reason": summary.skip_reason,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = parse_arguments()
    root = resolve_root(arguments)
    inbox = (
        Path(arguments.inbox).resolve()
        if arguments.inbox
        else root / "data" / "inbox"
    )
    importer = DataImporter(root, account_label=arguments.account)
    try:
        summaries = importer.import_directory(inbox)
    finally:
        importer.close()
    print(json.dumps([summary_to_dict(item) for item in summaries], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

