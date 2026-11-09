"""Parse MCP snapshots captured from the DouyinDataReview creator_read tool.

The snapshot format is written by the assistant when it pulls data through the
DouyinDataReview MCP (``creator_read``).  Field names follow the official
creator.douyin.com API payloads that DouyinDataReview itself consumes; see
ZhangYukwiver/DouyinDataReview src/domain/creatorCenter.ts for the reference
mapping this module mirrors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping


SNAPSHOT_SOURCE = "douyin-review-mcp"
SNAPSHOT_TOOL = "DouyinDataReview-MCP"

# creator API metric key -> canonical work_metrics column
METRIC_FIELDS: Mapping[str, str] = {
    "view_count": "play_count",
    "like_count": "like_count",
    "comment_count": "comment_count",
    "share_count": "share_count",
    "favorite_count": "collect_count",
    "subscribe_count": "follower_gain",
    "completion_rate": "completion_rate",
    "bounce_rate_2s": "two_second_bounce_rate",
    "cover_click_rate": "cover_click_rate",
}

PLAY_SOURCE_NAMES: Mapping[str, str] = {
    "homepage_hot": "推荐页",
    "search": "搜索",
    "homepage": "个人主页",
    "self_profile_vv_all": "个人主页",
    "other_profile_vv_all": "个人主页",
    "fresh": "同城页",
    "familiar": "朋友页",
    "follow": "关注页",
    "message": "消息页",
    "compilation": "合集",
    "order": "电商",
    "other": "其他",
    "yumme_vv_all": "精选App",
}


def is_mcp_snapshot(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("source") == SNAPSHOT_SOURCE
        and isinstance(payload.get("queries"), dict)
    )


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _unix_to_iso(value: Any) -> str | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    try:
        moment = datetime.fromtimestamp(number)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat(timespec="seconds")


def _work_status(aweme: Mapping[str, Any]) -> str | None:
    if _number((aweme.get("status") or {}).get("private_status")) == 1:
        return "私密"
    review_desc = (aweme.get("review_struct") or {}).get("status_desc")
    if review_desc:
        return str(review_desc)
    timer = aweme.get("timer") or {}
    if _number(timer.get("status")) in {0, 4, 5} and timer.get("public_time"):
        return "定时发布"
    status_value = _number(aweme.get("status_value"))
    if status_value in {102, 140, 143}:
        return "已发布"
    if status_value == 141:
        return "审核中"
    if status_value == 144:
        return "未通过"
    return None


def _metrics_hidden(aweme: Mapping[str, Any], metrics: Mapping[str, Any] | None) -> bool:
    """Mirror DouyinDataReview: private / reviewing works hide all metrics."""

    if metrics is None:
        return True
    review_status = _number((aweme.get("review_struct") or {}).get("status"))
    if review_status == 3:
        return False
    if (aweme.get("status") or {}).get("is_private"):
        return True
    if review_status in {1, 2, 4, 6}:
        return True
    status_value = _number(aweme.get("status_value"))
    if status_value == 141:
        return True
    return False


def _canonical_metrics(metrics: Mapping[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "play_count": None,
        "exposure_count": None,
        "like_count": None,
        "comment_count": None,
        "share_count": None,
        "collect_count": None,
        "follower_gain": None,
        "homepage_visits": None,
        "five_second_completion_rate": None,
        "completion_rate": None,
        "two_second_bounce_rate": None,
        "cover_click_rate": None,
    }
    if not metrics:
        return result
    for source_key, column in METRIC_FIELDS.items():
        value = metrics.get(source_key)
        if value is None or value == "":
            continue
        number = _number(value)
        if number is None or number < 0:
            continue
        is_count = column.endswith("_count") or column == "follower_gain"
        result[column] = int(number) if is_count else number
    return result


def parse_work_list_pages(pages: Iterable[Any]) -> list[dict[str, Any]]:
    """work_list pages: aweme_list entries joined with their items metrics."""

    works: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        items = page.get("items") or []
        metrics_by_id = {
            str(entry.get("id")): entry.get("metrics")
            for entry in items
            if isinstance(entry, Mapping)
        }
        for aweme in page.get("aweme_list") or []:
            if not isinstance(aweme, Mapping):
                continue
            video_id = str(aweme.get("aweme_id") or "")
            if not video_id.isdigit() or video_id in seen:
                continue
            seen.add(video_id)
            metrics = metrics_by_id.get(video_id)
            hidden = _metrics_hidden(aweme, metrics)
            duration_ms = _number(
                (aweme.get("video") or {}).get("duration") or aweme.get("duration")
            )
            timer = aweme.get("timer") or {}
            publish_ts = (
                timer.get("public_time")
                if _number(timer.get("status")) in {0, 4, 5} and timer.get("public_time")
                else aweme.get("create_time")
            )
            works.append(
                {
                    "video_id": video_id,
                    "title": str(aweme.get("desc") or "") or None,
                    "publish_time": _unix_to_iso(publish_ts),
                    "duration_seconds": (
                        int(round(duration_ms / 1000))
                        if duration_ms and duration_ms > 0
                        else None
                    ),
                    "status": _work_status(aweme),
                    "content_kind": "图文" if aweme.get("is_slides") else None,
                    "metrics": (
                        _canonical_metrics(None) if hidden else _canonical_metrics(metrics)
                    ),
                    "average_watch_duration_seconds": None,
                    "raw": dict(aweme),
                    "raw_metrics": None if hidden or not metrics else dict(metrics),
                }
            )
    return works


def parse_item_list_pages(pages: Iterable[Any]) -> list[dict[str, Any]]:
    """item_list pages (order-by flows): item entries carry metrics directly."""

    works: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            video_id = str(item.get("id") or "")
            if not video_id.isdigit() or video_id in seen:
                continue
            seen.add(video_id)
            metrics = item.get("metrics")
            duration_ms = _number((item.get("video_info") or {}).get("duration"))
            works.append(
                {
                    "video_id": video_id,
                    "title": str(item.get("description") or "") or None,
                    "publish_time": _unix_to_iso(item.get("create_time")),
                    "duration_seconds": (
                        int(round(duration_ms / 1000))
                        if duration_ms and duration_ms > 0
                        else None
                    ),
                    "status": (
                        "已发布" if _number((item.get("review") or {}).get("status")) == 2 else None
                    ),
                    "content_kind": None,
                    "metrics": _canonical_metrics(metrics),
                    "average_watch_duration_seconds": None,
                    "raw": dict(item),
                    "raw_metrics": dict(metrics) if metrics else None,
                }
            )
    return works


def parse_play_sources(entries: Iterable[Any]) -> dict[str, list[dict[str, Any]]]:
    """item_play_source entries -> {video_id: [{name, ratio}...]} (douyin app only)."""

    result: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        video_id = str(entry.get("item_id") or "")
        payload = entry.get("response")
        if not video_id or not isinstance(payload, Mapping):
            continue
        rows = None
        for candidate_key in ("play_source", "data", "list"):
            if isinstance(payload.get(candidate_key), list):
                rows = payload[candidate_key]
                break
        if rows is None:
            continue
        kept: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if _number(row.get("app_id")) != 1128:
                continue
            key = str(row.get("key") or "")
            value = _number(row.get("value"))
            if key not in PLAY_SOURCE_NAMES or value is None or value < 0.0005:
                continue
            name = PLAY_SOURCE_NAMES[key]
            kept[name] = round(kept.get(name, 0.0) + value, 6)
        if kept:
            result[video_id] = [
                {"name": name, "ratio": ratio}
                for name, ratio in sorted(kept.items(), key=lambda pair: -pair[1])
            ]
    return result


def parse_trends(entries: Iterable[Any]) -> dict[str, Any]:
    """item_trend entries -> {video_id: raw payload} for later analysis."""

    result: dict[str, Any] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        video_id = str(entry.get("item_id") or "")
        payload = entry.get("response")
        if video_id and payload is not None:
            result[video_id] = payload
    return result


FANS_DIMENSIONS: Mapping[str, str] = {
    "fans_sex_distribution": "性别分布",
    "fans_age_distribution": "年龄分布",
    "fans_city_distribution": "城市分布",
    "fans_active_degree_distribution": "活跃度分布",
    "fans_interest_distribution": "兴趣分布",
    "fans_device_price_distribution": "机型价位分布",
}


def parse_fans_summary(payload: Any) -> list[dict[str, Any]]:
    """fans_summary portrait groups -> fan_profiles rows (ratio based)."""

    if not isinstance(payload, Mapping):
        return []
    portrait = (
        payload.get("fans_portrait")
        if isinstance(payload.get("fans_portrait"), Mapping)
        else payload
    )
    rows: list[dict[str, Any]] = []
    for key, dimension in FANS_DIMENSIONS.items():
        group = portrait.get(key)
        if not isinstance(group, Mapping):
            continue
        items = group.get("items") if isinstance(group.get("items"), list) else group.get("data")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name") or item.get("key")
            ratio = _number(item.get("value"))
            if name is None or ratio is None:
                continue
            rows.append(
                {
                    "dimension": dimension,
                    "segment": str(name),
                    "value": None,
                    "ratio": ratio,
                }
            )
    return rows


def merge_works(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer work_list rows; fill gaps with item_list rows (dedupe by video_id)."""

    by_id = {work["video_id"]: work for work in primary}
    for work in secondary:
        existing = by_id.get(work["video_id"])
        if existing is None:
            by_id[work["video_id"]] = work
            continue
        for key, value in work.items():
            if value is None or existing.get(key):
                continue
            existing[key] = value
    return list(by_id.values())


def collected_at_from_snapshot(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("collected_at")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_snapshot_rows(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Turn one MCP snapshot payload into importable rows and issue context."""

    queries = payload.get("queries") or {}
    works = merge_works(
        parse_work_list_pages(queries.get("work_list") or []),
        parse_item_list_pages(queries.get("item_list") or []),
    )
    play_sources = parse_play_sources(queries.get("item_play_source") or [])
    trends = parse_trends(queries.get("item_trend") or [])

    for work in works:
        video_id = work["video_id"]
        enrichment: dict[str, Any] = {}
        raw_metrics = work.pop("raw_metrics", None)
        if raw_metrics:
            enrichment["metrics"] = raw_metrics
        if video_id in play_sources:
            enrichment["play_source"] = play_sources[video_id]
        if video_id in trends:
            enrichment["trend"] = trends[video_id]
        work["enrichment"] = enrichment

    fan_rows: list[dict[str, Any]] = []
    for entry in queries.get("fans_summary") or []:
        response = entry.get("response") if isinstance(entry, Mapping) else None
        fan_rows.extend(parse_fans_summary(response))

    return {
        "works": works,
        "fan_rows": fan_rows,
        "query_keys": sorted(key for key, value in queries.items() if value),
    }
