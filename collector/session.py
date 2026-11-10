"""Session storage for the douyin-direct collector.

The session file holds the account's own cookies (captured after a QR login)
plus the browser identity headers needed to make the creator-center read
endpoints accept our requests.  It stays on this machine, never enters Git
(``data/`` is ignored) and is never uploaded anywhere.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SESSION_VERSION = 1
LOGIN_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")


class SessionError(RuntimeError):
    """Raised when the session file is missing, invalid or expired."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_cookies(cookies: Any) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for cookie in cookies if isinstance(cookies, list) else []:
        if not isinstance(cookie, Mapping):
            continue
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        name = str(cookie.get("name") or "")
        value = cookie.get("value")
        if domain != "douyin.com" or not name or not isinstance(value, str):
            continue
        if any(char in value for char in ";\r\n"):
            continue
        kept.append(
            {
                "name": name,
                "value": value,
                "domain": cookie.get("domain") or ".douyin.com",
                "path": cookie.get("path") or "/",
                "expires": cookie.get("expires"),
            }
        )
    return kept


def build_session(
    *,
    cookies: list[dict[str, Any]],
    user_agent: str,
    request_headers: Mapping[str, str],
    uid: str | None = None,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    kept = valid_cookies(cookies)
    if not any(cookie["name"] in LOGIN_COOKIE_NAMES for cookie in kept):
        raise SessionError("登录 Cookie 缺失（没有 sessionid），请重新扫码登录。")
    if not user_agent or not user_agent.startswith("Mozilla/5.0"):
        raise SessionError("User-Agent 缺失或异常。")
    return {
        "version": SESSION_VERSION,
        "uid": uid,
        "userAgent": user_agent,
        "cookies": kept,
        "requestHeaders": dict(request_headers),
        "identity": dict(identity) if identity else None,
        "savedAt": _utc_now(),
    }


def save_session(path: Path, session: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(session, ensure_ascii=False, indent=2)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")


def load_session(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SessionError(
            f"会话文件不存在：{path}。先运行 py -3 collector/login.py 扫码登录。"
        ) from error
    except json.JSONDecodeError as error:
        raise SessionError(f"会话文件损坏：{path}") from error
    if payload.get("version") != SESSION_VERSION:
        raise SessionError("会话文件版本不兼容，请重新登录生成。")
    cookies = valid_cookies(payload.get("cookies"))
    if not any(cookie["name"] in LOGIN_COOKIE_NAMES for cookie in cookies):
        raise SessionError("会话中没有登录 Cookie（sessionid），请重新扫码登录。")
    user_agent = payload.get("userAgent")
    if not isinstance(user_agent, str) or not user_agent.startswith("Mozilla/5.0"):
        raise SessionError("会话缺少有效的 User-Agent，请重新登录。")
    payload["cookies"] = cookies
    return payload


def cookie_header(session: Mapping[str, Any]) -> str:
    """Build a Cookie header covering all douyin.com cookies."""

    pairs: list[str] = []
    for cookie in session["cookies"]:
        pairs.append(f"{cookie['name']}={cookie['value']}")
    return "; ".join(pairs)


def cookie_value(session: Mapping[str, Any], name: str) -> str | None:
    for cookie in session["cookies"]:
        if cookie["name"] == name and cookie.get("value"):
            return cookie["value"]
    return None


def safe_request_headers(session: Mapping[str, Any]) -> dict[str, str]:
    """Whitelisted browser identity headers captured at login time."""

    allowed = ("accept-language", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform")
    result: dict[str, str] = {}
    source = session.get("requestHeaders") or {}
    for name in allowed:
        value = source.get(name)
        if (
            isinstance(value, str)
            and value
            and len(value) <= 500
            and "\r" not in value
            and "\n" not in value
        ):
            result[name] = value
    return result
