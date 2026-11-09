"""Deterministic analysis over one stored works snapshot."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from .store import Database


CORE_FIELDS = (
    "play_count",
    "like_count",
    "comment_count",
    "share_count",
    "collect_count",
    "five_second_completion_rate",
    "completion_rate",
    "two_second_bounce_rate",
    "cover_click_rate",
    "average_watch_duration_seconds",
    "follower_gain",
)


def _values(rows: Sequence[Mapping[str, Any]], field: str) -> list[Any]:
    return [row[field] for row in rows if row.get(field) is not None]


def _number_or_none(value: Any) -> float | int | None:
    if value is None:
        return None
    return float(value)


def _average(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = _values(rows, field)
    return round(mean(values), 6) if values else None


def _median(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = _values(rows, field)
    return round(median(values), 6) if values else None


def _sum(rows: Sequence[Mapping[str, Any]], field: str) -> int | None:
    values = _values(rows, field)
    return sum(int(value) for value in values) if values else None


class TopicClassifier:
    def __init__(self, config_path: Path):
        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        self.topics = config.get("topics", [])
        self.fallback = config.get("fallback_topic", "其他")

    def classify(self, title: str | None) -> str:
        text = (title or "").lower()
        for topic in self.topics:
            keywords = [str(keyword).lower() for keyword in topic.get("keywords", [])]
            if any(keyword in text for keyword in keywords):
                return str(topic["name"])
        return self.fallback


class WorkAnalyzer:
    def __init__(
        self,
        database: Database,
        root: Path,
        snapshot_id: str,
    ):
        self.database = database
        self.root = root
        self.snapshot_id = snapshot_id
        snapshot = database.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"snapshot not found: {snapshot_id}")
        self.snapshot = dict(snapshot)
        self.rows = [dict(row) for row in database.work_metrics(snapshot_id)]
        self.classifier = TopicClassifier(root / "config" / "topics.json")
        with (root / "config" / "thresholds.json").open("r", encoding="utf-8") as handle:
            self.thresholds = json.load(handle)

    def build(self) -> dict[str, Any]:
        all_works = self._work_views()
        metric_works = [
            row for row in all_works if row.get("play_count") is not None
        ]
        recent = self._recent_works()
        topics = self._topics(metric_works)
        return {
            "snapshot": self.snapshot,
            "account_label": self.snapshot["account_label"],
            "coverage": self._coverage(),
            "works": self._overview(all_works, recent),
            "topics": topics,
            "play_sources": self._play_sources(),
            "daily_trends": self._daily_trends(),
            "comparison": self._comparison(),
            "diagnostics": self._diagnostics(metric_works),
            "skill_feedback": self._skill_feedback(metric_works, topics),
            "fan_profiles": self._fan_profiles(),
            "import_issues": [
                dict(row) for row in self.database.issues(self.snapshot_id)
            ],
        }

    def _daily_trends(self) -> dict[str, Any]:
        """Account-level daily metrics from the newest XLSX imports."""

        rows = [dict(row) for row in self.database.daily_metrics_rows(self.snapshot["account_label"])]
        if not rows:
            return {"available": False, "recent": [], "averages": {}}
        recent = rows[-14:]
        last7 = rows[-7:]
        averages: dict[str, Any] = {}
        for field in (
            "five_second_completion_rate",
            "two_second_bounce_rate",
            "cover_click_rate",
            "average_watch_duration_seconds",
        ):
            values = [row[field] for row in last7 if row.get(field) is not None]
            averages[field] = round(mean(values), 6) if values else None
        plays = [row["play_count"] for row in last7 if row.get("play_count") is not None]
        averages["play_count"] = round(mean(plays), 2) if plays else None
        gains = [row["follower_net"] for row in last7 if row.get("follower_net") is not None]
        averages["follower_net"] = round(mean(gains), 2) if gains else None
        return {
            "available": True,
            "date_range": [rows[0]["stat_date"], rows[-1]["stat_date"]],
            "row_count": len(rows),
            "averages": averages,
            "recent": recent,
        }

    def _comparison(self) -> dict[str, Any]:
        """Current works snapshot vs the previous one, aligned by video_id."""

        previous = self.database.previous_snapshot(
            self.snapshot["account_label"], self.snapshot["snapshot_id"], "works"
        )
        if previous is None:
            return {"available": False, "reason": "single_snapshot"}

        previous_rows = {
            row["video_id"]: row
            for row in self.database.work_metrics(previous["snapshot_id"])
            if row["play_count"] is not None
        }
        deltas: list[dict[str, Any]] = []
        new_works: list[dict[str, Any]] = []
        for row in self.rows:
            play = row.get("play_count")
            if play is None:
                continue
            before = previous_rows.get(row["video_id"])
            if before is None:
                if not (
                    play < int(self.thresholds["small_base_play_count"])
                ):
                    new_works.append(
                        {
                            "video_id": row["video_id"],
                            "title": row.get("title"),
                            "play_count": play,
                        }
                    )
                continue
            delta = play - int(before["play_count"])
            if delta == 0:
                continue
            deltas.append(
                {
                    "video_id": row["video_id"],
                    "title": row.get("title"),
                    "previous_play_count": int(before["play_count"]),
                    "play_count": play,
                    "delta": delta,
                }
            )

        current_plays = [row["play_count"] for row in self.rows if row.get("play_count") is not None]
        previous_plays = [int(row["play_count"]) for row in previous_rows.values()]
        avg_delta = None
        if current_plays and previous_plays:
            avg_delta = round(mean(current_plays) - mean(previous_plays), 2)
        movers = sorted(deltas, key=lambda item: -item["delta"])
        return {
            "available": True,
            "previous_snapshot_id": previous["snapshot_id"],
            "previous_collected_at": previous["collected_at"],
            "compared_work_count": len(deltas),
            "average_play_delta": avg_delta,
            "risers": movers[:5],
            "fallers": list(reversed(movers[-5:])),
            "new_works": sorted(
                new_works, key=lambda item: -int(item["play_count"])
            )[:5],
        }

    def _play_sources(self) -> dict[str, Any]:
        """Aggregate per-work traffic sources stored in work_metrics.raw_json."""

        weighted: dict[str, float] = defaultdict(float)
        total_weight = 0.0
        per_work: list[dict[str, Any]] = []
        for row in self.rows:
            try:
                raw = json.loads(row.get("raw_json") or "{}")
            except json.JSONDecodeError:
                continue
            sources = raw.get("play_source")
            if not isinstance(sources, list) or not sources:
                continue
            play_count = row.get("play_count")
            weight = float(play_count) if play_count else 0.0
            total_weight += weight
            entries: list[dict[str, Any]] = []
            for source in sources:
                if not isinstance(source, Mapping):
                    continue
                name = source.get("name")
                ratio = source.get("ratio")
                if name is None or ratio is None:
                    continue
                weighted[str(name)] += float(ratio) * weight
                entries.append({"name": str(name), "ratio": float(ratio)})
            per_work.append(
                {
                    "video_id": row["video_id"],
                    "title": row.get("title"),
                    "publish_time": row.get("publish_time"),
                    "play_count": play_count,
                    "small_base": (
                        play_count is not None
                        and play_count
                        < int(self.thresholds["small_base_play_count"])
                    ),
                    "sources": entries,
                }
            )

        if total_weight <= 0:
            non_empty = per_work[:]
            if not non_empty:
                return {"available": False, "aggregate": [], "works": []}
            # No play counts: fall back to an unweighted mean across works.
            totals: dict[str, float] = defaultdict(float)
            for work in non_empty:
                for entry in work["sources"]:
                    totals[entry["name"]] += entry["ratio"]
            aggregate = [
                {"name": name, "ratio": round(value / len(non_empty), 6)}
                for name, value in sorted(totals.items(), key=lambda pair: -pair[1])
            ]
            return {"available": True, "aggregate": aggregate, "works": per_work[:20]}

        aggregate = [
            {"name": name, "ratio": round(value / total_weight, 6)}
            for name, value in sorted(weighted.items(), key=lambda pair: -pair[1])
        ]
        return {
            "available": True,
            "aggregate": aggregate,
            "works": per_work[:20],
        }

    def _coverage(self) -> dict[str, Any]:
        present: list[str] = []
        missing: list[str] = []
        for field in CORE_FIELDS:
            if _values(self.rows, field):
                present.append(field)
            else:
                missing.append(field)
        return {
            "present_fields": present,
            "missing_fields": missing,
            "missing_core_fields": len(missing),
            "coverage_rate": round(len(present) / len(CORE_FIELDS), 4),
        }

    def _work_views(self, rows: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        source = self.rows if rows is None else rows
        for row in source:
            missing_fields = [
                field for field in CORE_FIELDS if row.get(field) is None
            ]
            play_count = row.get("play_count")
            result.append(
                {
                    "video_id": row["video_id"],
                    "title": row.get("title"),
                    "publish_time": row.get("publish_time"),
                    "topic": self.classifier.classify(row.get("title")),
                    "play_count": play_count,
                    "like_count": row.get("like_count"),
                    "comment_count": row.get("comment_count"),
                    "share_count": row.get("share_count"),
                    "collect_count": row.get("collect_count"),
                    "five_second_completion_rate": row.get(
                        "five_second_completion_rate"
                    ),
                    "completion_rate": row.get("completion_rate"),
                    "two_second_bounce_rate": row.get("two_second_bounce_rate"),
                    "cover_click_rate": row.get("cover_click_rate"),
                    "average_watch_duration_seconds": row.get(
                        "average_watch_duration_seconds"
                    ),
                    "follower_gain": row.get("follower_gain"),
                    "small_base": (
                        play_count is not None
                        and play_count
                        < int(self.thresholds["small_base_play_count"])
                    ),
                    "missing_fields": missing_fields,
                }
            )
        return result

    def _recent_works(self) -> list[dict[str, Any]]:
        return self._work_views(self.rows[:20])

    def _overview(
        self,
        all_works: Sequence[Mapping[str, Any]],
        recent: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        rows = [row for row in all_works if row.get("play_count") is not None]
        return {
            "total_work_count": len(all_works),
            "count": len(rows),
            "total_play_count": _sum(rows, "play_count"),
            "average_play_count": _average(rows, "play_count"),
            "median_play_count": _median(rows, "play_count"),
            "average_like_count": _average(rows, "like_count"),
            "average_comment_count": _average(rows, "comment_count"),
            "average_collect_count": _average(rows, "collect_count"),
            "average_share_count": _average(rows, "share_count"),
            "average_five_second_completion_rate": _average(
                rows, "five_second_completion_rate"
            ),
            "average_completion_rate": _average(rows, "completion_rate"),
            "average_two_second_bounce_rate": _average(
                rows, "two_second_bounce_rate"
            ),
            "recent": list(recent),
        }

    def _topics(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["topic"])].append(row)

        result: list[dict[str, Any]] = []
        for topic, topic_rows in grouped.items():
            plays = _sum(topic_rows, "play_count")
            engagement = sum(
                int(row.get(field) or 0)
                for row in topic_rows
                for field in ("like_count", "comment_count", "share_count", "collect_count")
            )
            total_plays = plays or 0
            result.append(
                {
                    "topic": topic,
                    "work_count": len(topic_rows),
                    "median_play_count": _median(topic_rows, "play_count"),
                    "median_completion_rate": _median(
                        topic_rows, "completion_rate"
                    ),
                    "interaction_rate": (
                        round(engagement / total_plays, 6) if total_plays else None
                    ),
                    "total_follower_gain": _sum(topic_rows, "follower_gain"),
                }
            )
        return sorted(result, key=lambda item: (-int(item["work_count"]), item["topic"]))

    def _diagnostics(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        conclusions: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        data_gaps: list[dict[str, Any]] = []

        daily = self._daily_trends()
        daily_five = daily.get("averages", {}).get("five_second_completion_rate")
        if daily_five is None:
            data_gaps.append(
                {
                    "type": "missing_five_second_completion",
                    "conclusion": "账号级5秒完播率缺失，不能判断开头留存趋势；导入「数据表现_短视频全量指标」XLSX 可补齐。",
                }
            )
        elif daily_five < float(self.thresholds["five_second_completion_good"]):
            conclusions.append(
                {
                    "type": "five_second_completion_low",
                    "conclusion": f"近7天账号级5秒完播率均值 {daily_five:.1%}，低于良好线，优先检查开头钩子与信息密度。",
                    "status": "初步判断",
                }
            )

        for row in rows:
            if row["small_base"]:
                observations.append(
                    {
                        "type": "small_base",
                        "video_id": row["video_id"],
                        "conclusion": (
                            f"播放量 {row['play_count']} 低于 "
                            f"{self.thresholds['small_base_play_count']}，只作观察，不做深度归因。"
                        ),
                    }
                )
                continue

            bounce = row.get("two_second_bounce_rate")
            if bounce is not None and bounce >= float(
                self.thresholds["two_second_bounce_warning"]
            ):
                conclusions.append(
                    {
                        "type": "opening_hook",
                        "video_id": row["video_id"],
                        "conclusion": "2秒跳出率达到预警线，优先检查开头钩子。",
                        "status": "初步判断",
                    }
                )

            five = row.get("five_second_completion_rate")
            completion = row.get("completion_rate")
            if (
                five is not None
                and completion is not None
                and five >= float(self.thresholds["five_second_completion_good"])
                and completion < 0.30
            ):
                conclusions.append(
                    {
                        "type": "middle_structure",
                        "video_id": row["video_id"],
                        "conclusion": "5秒留存达标但整体完播偏低，优先检查中段结构与节奏。",
                        "status": "初步判断",
                    }
                )

            play = row.get("play_count")
            if completion is not None and completion >= 0.30 and play is not None and play < 2000:
                conclusions.append(
                    {
                        "type": "distribution_or_packaging",
                        "video_id": row["video_id"],
                        "conclusion": "完播尚可但播放量偏低，检查选题、标题、封面和分发场景。",
                        "status": "初步判断",
                    }
                )

        sources = self._play_sources()
        if sources.get("available"):
            aggregate = {
                item["name"]: item["ratio"] for item in sources.get("aggregate", [])
            }
            recommend = aggregate.get("推荐页")
            search = aggregate.get("搜索")
            fan_flow = sum(
                aggregate.get(name, 0.0)
                for name in ("个人主页", "关注页", "朋友页", "消息页")
            )
            if recommend is not None and recommend < 0.50:
                conclusions.append(
                    {
                        "type": "traffic_recommend_weak",
                        "conclusion": (
                            f"推荐页流量占比 {recommend:.1%}，低于 50%，分发规模受限是播放回落的主要解释之一。"
                        ),
                        "status": "已证实",
                    }
                )
            if search is not None and search >= 0.20:
                conclusions.append(
                    {
                        "type": "traffic_search_strong",
                        "conclusion": (
                            f"搜索流量占比 {search:.1%}，标题与关键词命中有效，选题可继续加重搜索意图。"
                        ),
                        "status": "初步判断",
                    }
                )
            if fan_flow >= 0.30:
                conclusions.append(
                    {
                        "type": "traffic_fan_flow",
                        "conclusion": (
                            f"主页/关注/朋友等私域入口合计占比 {fan_flow:.1%}，系列内容与主页导流有效，但破圈流量不足。"
                        ),
                        "status": "初步判断",
                    }
                )
        else:
            data_gaps.append(
                {
                    "type": "missing_play_source",
                    "conclusion": "流量来源数据缺失，无法判断分发结构；接入 DouyinDataReview MCP 后可补齐。",
                }
            )

        conclusions.append(
            {
                "type": "review_rubric",
                "conclusion": "后续复盘固定观察：2秒跳出/开头钩子、5秒完播/信息密度、整体完播/中段结构、互动/结尾引导。",
                "status": "方法提醒",
            }
        )
        return {
            "conclusions": conclusions,
            "observations": observations,
            "data_gaps": data_gaps,
        }

    def _skill_feedback(
        self,
        rows: Sequence[Mapping[str, Any]],
        topics: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, str]]:
        feedback = [
            {
                "target": "douyin-operations",
                "action": "补充本次账号基准：播放中位数、完播中位数、2秒跳出中位数和小基数处理规则。",
            },
            {
                "target": "narrative-skill",
                "action": "把开头钩子拆成可 A/B 的两版：具体场景冲突版 vs 结论前置版。",
            },
        ]
        ranked = sorted(
            [item for item in topics if item.get("median_play_count") is not None],
            key=lambda item: float(item["median_play_count"]),
            reverse=True,
        )
        if ranked:
            winner = ranked[0]
            feedback.append(
                {
                    "target": "topic-radar",
                    "action": (
                        f"提高「{winner['topic']}」的选题权重；其播放中位数为 "
                        f"{winner['median_play_count']}。"
                    ),
                }
            )
        if any(row["small_base"] for row in rows):
            feedback.append(
                {
                    "target": "douyin-operations",
                    "action": "小基数作品不要归因，优先重做下一条或换钩子测试。",
                }
            )
        return feedback

    def _fan_profiles(self) -> dict[str, Any]:
        latest = self.database.latest_snapshot(
            self.snapshot["account_label"], "fan_profiles"
        )
        if latest is None:
            return {"available": False, "rows": []}
        return {
            "available": True,
            "snapshot_id": latest["snapshot_id"],
            "collected_at": latest["collected_at"],
            "rows": [dict(row) for row in self.database.fan_profiles(latest["snapshot_id"])],
        }

