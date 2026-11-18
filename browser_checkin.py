"""Use an independent browser to submit the official site's check-in form once.

No existing browser, profile, debugging port, verification widget, or token is
controlled. The official page performs its own challenge and submission.
"""

import os
import re
from urllib.parse import urlsplit

BASE_URL = "https://glados.cloud"
CHECKIN_PATH = "/api/user/checkin"
BUTTON_NAME = re.compile(r"^(check\s*in|签到|立即签到)$", re.IGNORECASE)


def parse_cookies(header):
    cookies = []
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies.append({
                "name": name, "value": value, "url": BASE_URL + "/",
                "secure": True,
            })
    return cookies


def is_checkin_response(response):
    url = urlsplit(response.url)
    return (url.scheme == "https" and url.netloc == "glados.cloud"
            and url.path == CHECKIN_PATH and response.request.method == "POST")


def submit_page(context):
    """Submit once; never retry a click whose outcome may be unknown."""
    page = context.new_page()
    page.set_default_timeout(45_000)
    print("浏览器: 打开官网签到页", flush=True)
    page.goto(BASE_URL + "/console/checkin", wait_until="domcontentloaded", timeout=45_000)
    button = page.get_by_role("button", name=BUTTON_NAME).first
    button.wait_for(state="visible", timeout=45_000)
    print("浏览器: 提交官网签到表单一次，等待页面完成正常验证", flush=True)
    with page.expect_response(is_checkin_response, timeout=150_000) as pending:
        button.click(timeout=45_000)
    response = pending.value
    if response.status != 200:
        return {"code": -1, "reason": "browser-http-error", "http_status": response.status}
    result = response.json()
    if not isinstance(result, dict):
        return {"code": -1, "reason": "browser-invalid-response"}
    print(f"浏览器: 官网签到响应 code={result.get('code')} reason={result.get('reason') or 'none'} repeated={result.get('repeated') is True}", flush=True)
    return result


def browser_checkin(cookie, user_agent=None):
    from playwright.sync_api import Error, TimeoutError, sync_playwright

    # launch() creates a dedicated process and temporary profile. Never connect
    # to an existing browser or use the user's default profile directory.
    channel = os.environ.get("GLADOS_BROWSER_CHANNEL", "chrome").strip()
    headless = os.environ.get("GLADOS_BROWSER_HEADLESS", "false").lower() == "true"
    try:
        with sync_playwright() as playwright:
            with playwright.chromium.launch(channel=channel or None, headless=headless) as browser:
                options = {"locale": "en-US"}
                if user_agent:
                    options["user_agent"] = user_agent
                with browser.new_context(**options) as context:
                    context.add_cookies(parse_cookies(cookie))
                    return submit_page(context)
    except TimeoutError:
        return {"code": -1, "reason": "browser-timeout",
                "message": "官网浏览器流程超时，结果不确定；请核对官网记录，不会自动再次提交。"}
    except Error:
        # Playwright exceptions can include cookie-bearing request diagnostics.
        return {"code": -1, "reason": "browser-error"}
