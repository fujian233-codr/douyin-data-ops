"""Render analyzer results as Markdown and JSON."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .analyzer import WorkAnalyzer
from .store import Database


@dataclass
class ReportResult:
    payload: dict[str, Any]
    markdown_path: Path
    json_path: Path


def _percent(value: Any) -> str:
    return "缺失" if value is None else f"{float(value) * 100:.2f}%"


def _count(value: Any) -> str:
    return "缺失" if value is None else f"{value:,}"


class ReportGenerator:
    def __init__(
        self,
        root: Path,
        account_label: str = "main",
        snapshot_id: str | None = None,
    ):
        self.root = root.resolve()
        self.account_label = account_label
        self.database = Database(self.root / "data" / "douyin.db")
        if snapshot_id is None:
            latest = self.database.latest_snapshot(account_label, "works")
            if latest is None:
                raise ValueError(f"no works snapshot for account: {account_label}")
            snapshot_id = str(latest["snapshot_id"])
        self.snapshot_id = snapshot_id

    def close(self) -> None:
        self.database.close()

    def generate(self) -> ReportResult:
        analysis = WorkAnalyzer(
            self.database, self.root, self.snapshot_id
        ).build()
        reports = self.root / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        markdown_path = reports / f"snapshot-{self.snapshot_id}.md"
        json_path = reports / f"snapshot-{self.snapshot_id}.json"
        markdown = self._markdown(analysis)
        markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
        json_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return ReportResult(analysis, markdown_path, json_path)

    def _markdown(self, data: Mapping[str, Any]) -> str:
        snapshot = data["snapshot"]
        coverage = data["coverage"]
        works = data["works"]
        lines: list[str] = [
            f"# 抖音账号数据复盘 · {data['account_label']}",
            "",
            f"- 数据来源：{snapshot['source_tool']}",
            f"- 快照 ID：{snapshot['snapshot_id']}",
            f"- 采集时间：{snapshot['collected_at']}",
            f"- 字段覆盖率：{coverage['coverage_rate']:.2%}",
            "",
            "## 一、数据覆盖情况",
            "",
            f"- 已覆盖字段：{', '.join(coverage['present_fields']) or '无'}",
            f"- 缺失字段：{', '.join(coverage['missing_fields']) or '无'}",
        ]
        if "five_second_completion_rate" in coverage["missing_fields"]:
            lines.append("- ⚠️ 5秒完播率缺失：开头留存判断暂不下结论。")

        lines.extend(
            [
                "",
                "## 二、账号总览",
                "",
                f"- 作品总数：{works['total_work_count']}",
                f"- 有播放指标作品数：{works['count']}",
                f"- 总播放：{_count(works['total_play_count'])}",
                f"- 平均播放：{_count(works['average_play_count'])}",
                f"- 播放中位数：{_count(works['median_play_count'])}",
                f"- 平均点赞：{_count(works['average_like_count'])}",
                f"- 平均评论：{_count(works['average_comment_count'])}",
                f"- 平均收藏：{_count(works['average_collect_count'])}",
                f"- 平均分享：{_count(works['average_share_count'])}",
                f"- 平均完播率：{_percent(works['average_completion_rate'])}",
                f"- 平均2秒跳出率：{_percent(works['average_two_second_bounce_rate'])}",
                f"- 平均5秒完播率：{_percent(works['average_five_second_completion_rate'])}",
                "",
                "## 三、最新作品表现",
                "",
                "| 发布时间 | 标题 | 题材 | 播放 | 完播 | 2秒跳出 | 涨粉 | 标记 |",
                "|---|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in works["recent"]:
            flags = []
            if row["small_base"]:
                flags.append("小基数")
            if row["missing_fields"]:
                flags.append(f"缺{len(row['missing_fields'])}项")
            lines.append(
                "| {publish} | {title} | {topic} | {play} | {completion} | {bounce} | {follow} | {flags} |".format(
                    publish=row["publish_time"] or "未知",
                    title=str(row["title"] or "无标题")
                    .replace("|", "/")
                    .replace("\r", " ")
                    .replace("\n", " "),
                    topic=row["topic"],
                    play=_count(row["play_count"]),
                    completion=_percent(row["completion_rate"]),
                    bounce=_percent(row["two_second_bounce_rate"]),
                    follow=_count(row["follower_gain"]),
                    flags="、".join(flags) or "—",
                )
            )

        lines.extend(["", "## 四、题材模式", ""])
        if data["topics"]:
            lines.append(
                "| 题材 | 作品数 | 播放中位数 | 完播中位数 | 互动率 | 涨粉 |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|")
            for topic in data["topics"]:
                lines.append(
                    f"| {topic['topic']} | {topic['work_count']} | "
                    f"{_count(topic['median_play_count'])} | "
                    f"{_percent(topic['median_completion_rate'])} | "
                    f"{_percent(topic['interaction_rate'])} | "
                    f"{_count(topic['total_follower_gain'])} |"
                )
        else:
            lines.append("暂无可分组作品。")

        play_sources = data.get("play_sources") or {}
        lines.extend(["", "## 五、流量来源结构", ""])
        if play_sources.get("available"):
            lines.append("| 来源 | 加权占比 |")
            lines.append("|---|---:|")
            for item in play_sources["aggregate"]:
                lines.append(f"| {item['name']} | {_percent(item['ratio'])} |")
            lines.extend(["", "### 作品流量来源明细", ""])
            work_rows = [
                work
                for work in play_sources.get("works", [])
                if not work.get("small_base")
            ]
            if work_rows:
                lines.append("| 发布时间 | 标题 | 播放 | 主要来源 |")
                lines.append("|---|---|---:|---|")
                for work in work_rows:
                    top = work["sources"][:3]
                    source_text = "、".join(
                        f"{entry['name']}{float(entry['ratio']):.0%}"
                        for entry in top
                    )
                    lines.append(
                        "| {publish} | {title} | {play} | {sources} |".format(
                            publish=work.get("publish_time") or "未知",
                            title=str(work.get("title") or "无标题")
                            .replace("|", "/")
                            .replace("\r", " ")
                            .replace("\n", " "),
                            play=_count(work.get("play_count")),
                            sources=source_text or "—",
                        )
                    )
            else:
                lines.append("有小基数据限制，暂无可展示的非小基数作品来源明细。")
        else:
            lines.append(
                "流量来源数据缺失；通过 DouyinDataReview MCP 拉取 `item_play_source` 后可补齐。"
            )

        diagnostics = data["diagnostics"]
        lines.extend(["", "## 六、诊断结论", "", "### 已证实 / 初步判断", ""])
        if diagnostics["conclusions"]:
            for item in diagnostics["conclusions"]:
                lines.append(f"- [{item['status']}] {item['conclusion']}")
        else:
            lines.append("- 暂无足够数据形成判断。")
        lines.extend(["", "### 小基数观察", ""])
        if diagnostics["observations"]:
            for item in diagnostics["observations"]:
                lines.append(f"- {item['conclusion']}")
        else:
            lines.append("- 无小基数作品。")
        lines.extend(["", "### 数据缺口", ""])
        if diagnostics["data_gaps"]:
            for item in diagnostics["data_gaps"]:
                lines.append(f"- {item['conclusion']}")
        else:
            lines.append("- 暂无核心数据缺口。")

        lines.extend(["", "## 七、Skill 与工作流反馈", ""])
        for item in data["skill_feedback"]:
            lines.append(f"- **{item['target']}**：{item['action']}")

        lines.extend(
            [
                "",
                "## 八、导入问题",
                "",
            ]
        )
        if data["import_issues"]:
            for issue in data["import_issues"]:
                lines.append(
                    f"- 第 {issue['row_number']} 行 / {issue['field_name']}："
                    f"{issue['issue_type']}（原始值：{issue['raw_value']}）"
                )
        else:
            lines.append("- 无。")
        lines.append("")
        return "\n".join(lines)

