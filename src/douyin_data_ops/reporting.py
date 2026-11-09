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
            lines.append("- ⚠️ 作品级5秒完播率缺失：单条开头留存判断暂不下结论（账号级见「每日趋势」）。")

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
                "## 三、每日趋势（账号级）",
                "",
            ]
        )
        daily = data.get("daily_trends") or {}
        if daily.get("available"):
            averages = daily["averages"]
            duration_avg = averages.get("average_watch_duration_seconds")
            fans_avg = averages.get("follower_net")
            lines.extend(
                [
                    f"- 覆盖区间：{daily['date_range'][0]} ~ {daily['date_range'][1]}（{daily['row_count']} 天）",
                    f"- 近7天平均播放：{_count(averages.get('play_count'))}",
                    f"- 近7天5秒完播率均值：{_percent(averages.get('five_second_completion_rate'))}",
                    f"- 近7天2秒跳出率均值：{_percent(averages.get('two_second_bounce_rate'))}",
                    f"- 近7天平均播放时长：{f'{duration_avg:.2f}s' if duration_avg is not None else '缺失'}",
                    f"- 近7天日均粉丝净增：{f'{fans_avg:+.1f}' if fans_avg is not None else '缺失'}",
                    "",
                    "| 日期 | 播放 | 5秒完播 | 2秒跳出 | 平均时长 | 粉丝净增 |",
                    "|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in daily["recent"]:
                duration = row.get("average_watch_duration_seconds")
                lines.append(
                    "| {date} | {play} | {five} | {bounce} | {duration} | {fans} |".format(
                        date=row["stat_date"],
                        play=_count(row.get("play_count")),
                        five=_percent(row.get("five_second_completion_rate")),
                        bounce=_percent(row.get("two_second_bounce_rate")),
                        duration=f"{duration:.2f}s" if duration is not None else "缺失",
                        fans=(
                            f"{row['follower_net']:+,}"
                            if row.get("follower_net") is not None
                            else "缺失"
                        ),
                    )
                )
        else:
            lines.append(
                "每日账号级数据缺失；把「数据表现_短视频全量指标 / 粉丝全量指标」XLSX 放入 `data/inbox/` 后重跑导入即可补齐 5 秒完播率等字段。"
            )

        lines.extend(
            [
                "",
                "## 四、最新作品表现",
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

        lines.extend(["", "## 五、题材模式", ""])
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

        comparison = data.get("comparison") or {}
        lines.extend(["", "## 六、环比（vs 上一快照）", ""])
        if comparison.get("available"):
            delta = comparison.get("average_play_delta")
            if delta is None:
                delta_text = "缺失"
            elif delta == 0:
                delta_text = "持平"
            else:
                delta_text = f"{delta:+,.0f}"
            lines.extend(
                [
                    f"- 对比快照：{comparison['previous_snapshot_id']}（采集于 {comparison['previous_collected_at']}）",
                    f"- 有指标作品平均播放变化：{delta_text}",
                    f"- 涨幅前五：{self._movers_text(comparison.get('risers'))}",
                    f"- 跌幅前五：{self._movers_text(comparison.get('fallers'))}",
                ]
            )
            if comparison.get("new_works"):
                titles = "、".join(
                    f"《{work['title'] or work['video_id']}》（{work['play_count']:,}播放）"
                    for work in comparison["new_works"]
                )
                lines.append(f"- 新增非小基数作品：{titles}")
        else:
            lines.append("暂无可对比的历史快照；下一次拉数后自动生成环比。")

        play_sources = data.get("play_sources") or {}
        lines.extend(["", "## 七、流量来源结构", ""])
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
        lines.extend(["", "## 八、诊断结论", "", "### 已证实 / 初步判断", ""])
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

        lines.extend(["", "## 九、Skill 与工作流反馈", ""])
        for item in data["skill_feedback"]:
            lines.append(f"- **{item['target']}**：{item['action']}")

        lines.extend(
            [
                "",
                "## 十、导入问题",
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

    @staticmethod
    def _movers_text(movers: list[dict[str, Any]] | None) -> str:
        if not movers:
            return "无"
        return "、".join(
            f"《{item['title'] or item['video_id']}》{item['delta']:+,}"
            for item in movers
        )

