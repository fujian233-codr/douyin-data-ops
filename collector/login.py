"""QR login for the douyin-direct collector.

Opens a visible Chromium window at creator.douyin.com; the user scans the QR
code with the Douyin app.  On success we export the account's own cookies plus
browser identity headers into data/session.json (mode 0600, never committed).

Requires the optional dependency: py -3 -m pip install playwright
followed by: playwright install chromium
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


COLLECTOR_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = COLLECTOR_DIRECTORY.parent
if str(COLLECTOR_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(COLLECTOR_DIRECTORY))

from session import build_session, save_session  # noqa: E402


LOGIN_TIMEOUT_SECONDS = 5 * 60
USER_INFO_PATH = (
    "/aweme/v1/creator/user/info/"
    "?aid=2906&app_name=aweme_creator_platform&device_platform=web"
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抖音创作者中心扫码登录（douyin-direct）")
    parser.add_argument(
        "--session",
        default=str(PROJECT_ROOT / "data" / "session.json"),
        help="会话文件路径，默认 <仓库根>/data/session.json",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 Playwright。安装：py -3 -m pip install playwright && playwright install chromium")
        return 1

    session_path = Path(arguments.session)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        print("正在打开 creator.douyin.com，请用抖音 App 扫码登录……")
        page.goto("https://creator.douyin.com/", wait_until="domcontentloaded")

        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
        logged_in = False
        while time.monotonic() < deadline:
            cookies = context.cookies("https://www.douyin.com")
            names = {cookie["name"] for cookie in cookies}
            if names & {"sessionid", "sessionid_ss", "sid_tt", "sid_guard"}:
                logged_in = True
                break
            page.wait_for_timeout(1000)

        if not logged_in:
            browser.close()
            print("等待扫码超时（5 分钟），未检测到登录态。重新运行再试。")
            return 1

        page.wait_for_timeout(3000)  # let secondary cookies settle

        # Same-origin identity read inside the logged-in page: cookies attach
        # automatically and no extra session plumbing is needed.
        identity = None
        uid = None
        try:
            payload = page.evaluate(
                "async (path) => { const r = await fetch(path, {credentials: 'include'});"
                " return await r.json(); }",
                USER_INFO_PATH,
            )
            user = (payload or {}).get("douyin_user_verify_info") or {}
            uid = str(user.get("douyin_uid") or "")
            identity = {
                "nickname": user.get("nick_name"),
                "follower_count": user.get("follower_count"),
                "unique_id": user.get("douyin_unique_id"),
            }
        except Exception:
            pass

        user_agent = page.evaluate("() => navigator.userAgent")
        request_headers = page.evaluate(
            """() => {
                const data = navigator.userAgentData || {};
                return {
                    'accept-language': navigator.language + ',' + (navigator.language || 'zh-CN'),
                    'sec-ch-ua': data.brands ? data.brands.map(b => `"${b.brand}";v="${b.version}"`).join(',') : undefined,
                    'sec-ch-ua-mobile': data.mobile === undefined ? undefined : String(data.mobile),
                    'sec-ch-ua-platform': (data.platform || '').toLowerCase() || undefined
                };
            }"""
        )
        cookies = context.cookies("https://www.douyin.com") + context.cookies(
            "https://creator.douyin.com"
        )
        browser.close()

    request_headers = {
        name: value for name, value in (request_headers or {}).items() if value
    }
    session = build_session(
        cookies=cookies,
        user_agent=user_agent,
        request_headers=request_headers,
        uid=uid,
        identity=identity,
    )
    save_session(session_path, session)
    if identity:
        print(
            f"登录成功：{identity.get('nickname')}"
            f"（粉丝 {identity.get('follower_count')}，抖音号 {identity.get('unique_id')}）"
        )
        print("请核对以上是不是目标账号；不是的话本会话不要用于拉数。")
    else:
        print("登录成功（未能读取账号身份，拉数时 pull.py 会再次核验）。")
    print(f"会话已保存：{session_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
