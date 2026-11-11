"""Full creator-data pull for the douyin-direct collector.

Step 0 is a mandatory identity check (nickname + follower count) so a wrong
account can never silently enter the pipeline.  The pull writes a snapshot
JSON that the existing importer understands (source: "douyin-direct").
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


COLLECTOR_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = COLLECTOR_DIRECTORY.parent
for entry in (str(COLLECTOR_DIRECTORY),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import api  # noqa: E402
from session import load_session, SessionError  # noqa: E402


SNAPSHOT_SOURCE = "douyin-direct"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拉取本人抖音创作者中心数据（douyin-direct）")
    parser.add_argument(
        "--session",
        default=str(PROJECT_ROOT / "data" / "session.json"),
        help="会话文件路径，默认 <仓库根>/data/session.json",
    )
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "data" / "inbox"),
        help="快照输出目录，默认 <仓库根>/data/inbox",
    )
    parser.add_argument(
        "--expect-nickname",
        help="期望账号昵称；提供后身份不符会立即停止",
    )
    parser.add_argument(
        "--deep-dive",
        type=int,
        default=20,
        help="深挖的最新有指标作品数，默认 20",
    )
    return parser.parse_args()


def verify_identity(session: dict, expected_nickname: str | None) -> dict:
    identity = api.identity(session)
    print(
        f"[身份核验] 昵称：{identity.get('nickname')}  "
        f"粉丝：{identity.get('follower_count')}  抖音号：{identity.get('unique_id')}"
    )
    if expected_nickname and identity.get("nickname") != expected_nickname:
        raise SystemExit(
            f"[身份核验] 昵称与期望（{expected_nickname}）不符，已停止。"
            "如确认要拉此账号，请去掉 --expect-nickname 或更新期望值。"
        )
    if not identity.get("nickname"):
        raise SystemExit("[身份核验] 无法读取账号身份，已停止；请重新运行 login.py。")
    return identity


def pull_work_list(session: dict) -> tuple[list[dict], list[dict]]:
    pages: list[dict] = []
    works: list[dict] = []
    seen: set[str] = set()
    cursor = "0"
    for page_number in range(1, 61):
        payload = api.fetch(
            session,
            "work_list",
            {"status": "0", "count": "20", "max_cursor": cursor},
        )
        pages.append(payload)
        metrics = {
            str(entry.get("id")): entry.get("metrics")
            for entry in payload.get("items") or []
            if isinstance(entry, dict)
        }
        fresh = 0
        for aweme in payload.get("aweme_list") or []:
            video_id = str(aweme.get("aweme_id") or "")
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            fresh += 1
            works.append(
                {
                    "video_id": video_id,
                    "view_count": (metrics.get(video_id) or {}).get("view_count"),
                }
            )
        print(
            f"  work_list 第{page_number}页：新增 {fresh} 条，"
            f"has_more={payload.get('has_more')}"
        )
        if not payload.get("has_more") or str(payload.get("max_cursor")) == cursor:
            break
        cursor = str(payload.get("max_cursor"))
    return pages, works


def deep_dive(session: dict, works: list[dict], limit: int) -> dict[str, list[dict]]:
    metric_works = [work for work in works if work["view_count"] is not None][:limit]
    result: dict[str, list[dict]] = {
        "item_play_source": [],
        "item_trend": [],
        "item_summarize": [],
    }
    for key in result:
        ok_count = 0
        for work in metric_works:
            try:
                params = {"item_id": work["video_id"]}
                if key == "item_trend":
                    # Official page shape: 累计趋势、按天、核心指标组。
                    params.update(
                        {
                            "trend_type": "2",
                            "time_unit": "1",
                            "metrics_group": "0,1,3",
                            "metrics": "view_count",
                        }
                    )
                payload = api.fetch(session, key, params)
                ok_count += 1
                result[key].append(
                    {"item_id": work["video_id"], "ok": True, "response": payload}
                )
            except api.CollectorError as error:
                result[key].append(
                    {"item_id": work["video_id"], "ok": False, "response": None}
                )
                if error.code == "login_required":
                    raise
        print(f"  {key}: {ok_count}/{len(metric_works)} ok")
    return result


def main() -> int:
    arguments = parse_arguments()
    try:
        session = load_session(Path(arguments.session))
    except SessionError as error:
        print(f"[会话] {error}")
        return 1

    print("[0/4] 身份核验")
    verify_identity(session, arguments.expect_nickname)

    print("[1/4] 账号总览")
    overview = {
        "user_info": [api.fetch(session, "user_info")],
        "fans_summary": [{"response": api.fetch(session, "fans_summary")}],
        "dashboard": [
            api.fetch(session, "dashboard", {"recent_days": "7"}),
            api.fetch(session, "dashboard", {"recent_days": "30"}),
        ],
        "dashboard_fans": [
            api.fetch(session, "dashboard_fans", {"recent_days": "7"}),
            api.fetch(session, "dashboard_fans", {"recent_days": "30"}),
        ],
    }

    print("[2/4] 作品全量")
    pages, works = pull_work_list(session)
    metric_count = sum(1 for work in works if work["view_count"] is not None)
    print(f"  共 {len(works)} 条作品，{metric_count} 条有指标")

    print("[3/4] 重点作品深挖")
    deep = deep_dive(session, works, arguments.deep_dive)

    snapshot = {
        "source": SNAPSHOT_SOURCE,
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "queries": {
            **overview,
            "work_list": pages,
            "item_play_source": deep["item_play_source"],
            "item_trend": deep["item_trend"],
            "item_summarize": deep["item_summarize"],
        },
    }
    out_directory = Path(arguments.out)
    out_directory.mkdir(parents=True, exist_ok=True)
    name = "direct-" + datetime.now().strftime("%Y%m%d-%H%M") + ".json"
    path = out_directory / name
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    print(f"[4/4] 快照已保存：{path}（{path.stat().st_size / 1024:.0f} KB）")
    print("下一步：py -3 scripts/import_data.py --inbox data/inbox --account main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
