"""Read-only creator-center API client for the douyin-direct collector.

The endpoint whitelist, query shapes and error semantics are ported from
ZhangYukwiver/DouyinDataReview (MIT License,
https://github.com/ZhangYukwiver/DouyinDataReview), collector/creatorCenter.mjs
and collector/directApi.mjs.  Requests replay the official creator.douyin.com
web frontend's own calls with the account's saved cookies; these endpoints do
not require a_bogus signing.  Read-only: no write endpoint exists here.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from session import SessionError, cookie_header, cookie_value, safe_request_headers


ORIGIN = "https://creator.douyin.com"
MAX_BYTES = 24 * 1024 * 1024
THROTTLE_SECONDS = 0.35

CREATOR_QUERY = {"aid": "2906", "app_name": "aweme_creator_platform", "device_platform": "web"}
WORK_LIST_QUERY = {"aid": "1128", "scene": "star_atlas", "device_platform": "android"}

# key -> endpoint definition.  Mirrors the read-only creator whitelist.
CREATOR_ENDPOINTS: dict[str, dict[str, Any]] = {
    "user_info": {"path": "/aweme/v1/creator/user/info/", "params": []},
    "dashboard": {
        "method": "POST",
        "path": "/janus/douyin/creator/data/overview/dashboard",
        "params": ["recent_days"],
        "body": True,
    },
    "dashboard_fans": {
        "path": "/janus/douyin/creator/data/overview/dashboard/fans",
        "params": ["recent_days"],
    },
    "fans_summary": {"path": "/janus/douyin/creator/bff/data/fans/summary/v2", "params": []},
    "work_list": {
        "path": "/janus/douyin/creator/pc/work_list",
        "query": WORK_LIST_QUERY,
        "params": ["status", "count", "max_cursor", "min_cursor"],
    },
    "item_list": {
        "path": "/web/api/creator/item/list",
        "params": ["user_id", "count", "order_by", "start_time", "end_time", "min_cursor", "max_cursor"],
    },
    "item_play_source": {
        "path": "/janus/douyin/creator/data/item/play/source",
        "params": ["item_id"],
    },
    "item_trend": {
        "path": "/janus/douyin/creator/data/item_analysis/metrics_trend",
        "params": ["item_id", "trend_type", "time_unit", "metrics_group", "metrics"],
    },
    "item_summarize": {
        "path": "/janus/douyin/creator/data/item/summarize/",
        "params": ["item_id"],
    },
}

PARAM_VALUE = re.compile(r"^[\w,.:@/+=-]{0,160}$")
LOGIN_STATUS_CODES = {8, 2190008, 10008}

_last_request = 0.0


class CollectorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def creator_request(key: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate key+params against the whitelist and build {method,url,body}."""

    endpoint = CREATOR_ENDPOINTS.get(key)
    supplied = dict(params or {})
    if endpoint is None or not isinstance(supplied, dict):
        return {}
    picked: dict[str, str] = {}
    for name, value in supplied.items():
        if value is None:
            continue
        if name not in endpoint["params"]:
            return {}
        text = str(value)
        if not PARAM_VALUE.match(text):
            return {}
        picked[name] = text
    method = endpoint.get("method", "GET")
    query_pairs: list[tuple[str, str]] = list(endpoint.get("query", CREATOR_QUERY).items())
    body = None
    if endpoint.get("body"):
        body = json.dumps(
            {
                name: int(value) if value.isdigit() and len(value) < 16 else value
                for name, value in picked.items()
            }
        )
    else:
        query_pairs.extend(picked.items())
    from urllib.parse import urlencode

    return {"method": method, "url": f"{ORIGIN}{endpoint['path']}?{urlencode(query_pairs)}", "body": body}


def _throttle() -> None:
    global _last_request
    wait = _last_request + THROTTLE_SECONDS - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def fetch(session: Mapping[str, Any], key: str, params: Mapping[str, Any] | None = None) -> Any:
    """Fetch one whitelisted creator endpoint; raises CollectorError on failure."""

    prepared = creator_request(key, params)
    if not prepared:
        raise CollectorError("invalid_request", f"请求不在白名单内或参数不合法：{key}")
    headers = {
        **safe_request_headers(session),
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{ORIGIN}/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "priority": "u=1, i",
        "User-Agent": session["userAgent"],
        "Cookie": cookie_header(session),
    }
    uifid = cookie_value(session, "UIFID")
    if uifid:
        headers["uifid"] = uifid
    data = None
    if prepared["body"] is not None:
        headers["Content-Type"] = "application/json"
        data = prepared["body"].encode("utf-8")

    request = urllib.request.Request(prepared["url"], data=data, headers=headers, method=prepared["method"])
    _throttle()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read(MAX_BYTES + 1) if error.fp else b""
    except urllib.error.URLError as error:
        raise CollectorError("network_error", f"网络请求失败：{error.reason}") from error

    if status in (401, 403):
        raise CollectorError("login_required", f"抖音接口返回 HTTP {status}，请重新扫码登录。")
    if status == 429:
        raise CollectorError("rate_limited", "抖音接口触发限流，已停止读取。")
    if status != 200:
        raise CollectorError("http_error", f"抖音接口返回 HTTP {status}。")
    if len(raw) > MAX_BYTES:
        raise CollectorError("response_too_large", "接口响应超过读取容量。")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectorError("invalid_json", "抖音接口没有返回有效 JSON。") from error
    if not isinstance(payload, dict):
        raise CollectorError("schema_changed", "抖音接口数据格式发生变化。")
    code = payload.get("status_code")
    if code in LOGIN_STATUS_CODES or code == "8":
        raise CollectorError("login_required", "登录已失效，请重新扫码登录。")
    if code is not None and code != 0:
        raise CollectorError("platform_rejected", f"抖音未确认本次请求（status_code={code}）。")
    return payload


def identity(session: Mapping[str, Any]) -> dict[str, Any]:
    """user_info as a compact identity record for the mandatory step-0 check."""

    info = fetch(session, "user_info")
    user = info.get("douyin_user_verify_info") or {}
    return {
        "uid": str(user.get("douyin_uid") or info.get("uid") or ""),
        "nickname": user.get("nick_name"),
        "follower_count": user.get("follower_count"),
        "unique_id": user.get("douyin_unique_id"),
    }
