"""Windows local check-in with a dedicated browser profile, never a personal one."""

import argparse
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from browser_checkin import BASE_URL, standalone_context, submit_page
from checkin import classify_checkin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true", help="Wait for you to sign in in the NEW dedicated window")
    parser.add_argument("--setup", action="store_true", help="Keep the dedicated window open for first-time user verification")
    parser.add_argument("--profile", default=str(Path(os.environ["LOCALAPPDATA"]) / "GLaDOSCheckin" / "BrowserProfile"))
    parser.add_argument("--channel", default="msedge", choices=("chrome", "msedge"))
    args = parser.parse_args()
    with sync_playwright() as playwright:
        with standalone_context(playwright, args.channel, profile_directory=args.profile) as context:
            page = context.new_page()
            page.goto(BASE_URL + "/console/checkin", wait_until="domcontentloaded", timeout=45_000)
            if args.setup:
                complete = Path(args.profile) / ".setup-complete"
                complete.unlink(missing_ok=True)
                print("专用 Edge 窗口已打开并保持：请在新窗口正常签到、完成必要验证。", flush=True)
                deadline = time.monotonic() + 900
                while not complete.is_file() and time.monotonic() < deadline:
                    page.wait_for_timeout(1000)
                print("专用窗口首次设置结束；下一步需要独立自动运行验证。", flush=True)
                return 0 if complete.is_file() else 2
            deadline = time.monotonic() + (600 if args.login else 5)
            print("本机独立浏览器: 等待官网登录；仅操作新建的专用窗口。", flush=True)
            while True:
                response = context.request.get(BASE_URL + "/api/user/status", timeout=20_000)
                status = response.json() if response.ok else {}
                if isinstance(status, dict) and status.get("code") in (0, "0") and isinstance(status.get("data"), dict):
                    break
                if time.monotonic() >= deadline:
                    print("需要在专用窗口登录，执行 local_checkin.py --login 后完成官网认证。", flush=True)
                    return 2
                page.wait_for_timeout(3000)
            print("本机独立浏览器: 登录有效，开始官网正常签到流程。", flush=True)
            result = submit_page(context)
            kind, message, points = classify_checkin(result)
            print(f"本机签到结果: {kind}; {message}; 本次积分={points}", flush=True)
            return 0 if kind in ("success", "repeat") else 2 if kind == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
