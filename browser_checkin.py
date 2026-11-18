"""Use an independent browser to submit the official site's check-in form once.

No existing browser, profile, debugging port, verification widget, or token is
controlled. The official page performs its own challenge and submission.
"""

import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from urllib.parse import urlsplit

BASE_URL = "https://glados.cloud"
CHECKIN_PATH = "/api/user/checkin"
BUTTON_NAME = re.compile(r"^(check\s*in|签到|立即签到)$", re.IGNORECASE)


def browser_executable(channel):
    relative = {
        "chrome": "Google/Chrome/Application/chrome.exe",
        "msedge": "Microsoft/Edge/Application/msedge.exe",
    }
    if channel not in relative:
        raise RuntimeError("Unsupported browser channel")
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root and (Path(root) / relative[channel]).is_file():
            return str(Path(root) / relative[channel])
    raise RuntimeError("Browser executable unavailable")


@contextmanager
def profile_lock(profile):
    """Prevent overlapping local runs; the OS releases the lock after a crash."""
    with open(profile / ".glados-run.lock", "a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("Dedicated browser profile is already in use") from None
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Dedicated browser profile is already in use") from None
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def standalone_context(playwright, channel, headless=False, user_agent=None, profile_directory=None):
    """Start our own browser and attach only to its randomly assigned local port.

    A unique empty profile prevents Chrome from reusing a personal browser.
    No shared debugging endpoint, existing profile, or external port is used.
    """
    executable = browser_executable(channel)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if profile_directory:
        owned = Path(profile_directory).resolve()
        owned.mkdir(parents=True, exist_ok=True)
        marker = owned / ".glados-checkin-profile"
        if not marker.is_file():
            if any(owned.iterdir()):
                raise RuntimeError("Refusing to use an existing personal browser profile")
            marker.write_text("Dedicated GLaDOS check-in browser only\n", encoding="utf-8")
        directory_context = nullcontext(str(owned))
    else:
        directory_context = tempfile.TemporaryDirectory(prefix="glados-browser-", dir=temp_root)
    with directory_context as directory:
        profile = Path(directory).resolve()
        if not profile_directory and (profile.parent != temp_root or not profile.name.startswith("glados-browser-")):
            raise RuntimeError("Unexpected temporary profile location")
        with profile_lock(profile):
            args = [executable, f"--user-data-dir={profile}", "--remote-debugging-port=0",
                    "--remote-debugging-address=127.0.0.1", "--no-first-run",
                    "--no-default-browser-check", "about:blank"]
            if headless:
                args.insert(-1, "--headless=new")
            active_port = profile / "DevToolsActivePort"
            active_port.unlink(missing_ok=True)
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            browser = None
            try:
                deadline = time.monotonic() + 30
                while not active_port.is_file():
                    if time.monotonic() >= deadline or process.poll() is not None:
                        raise RuntimeError("Independent browser did not start")
                    time.sleep(0.1)
                port = int(active_port.read_text(encoding="utf-8").splitlines()[0])
                if not 1 <= port <= 65535:
                    raise RuntimeError("Invalid browser debugging port")
                browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15_000)
                context = browser.new_context(user_agent=user_agent) if user_agent else browser.contexts[0]
                yield context
            finally:
                if browser:
                    try:
                        browser.new_browser_cdp_session().send("Browser.close")
                    except Exception:
                        pass
                    browser.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)


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
    payload = response.request.post_data_json
    state = "unknown"
    if isinstance(payload, dict):
        state = payload.get("tsState")
        state = state if state in ("ok", "off", "error", "timeout") else "unknown"
        print(f"浏览器: 官网请求 tsState={state} turnstile_present={bool(payload.get('turnstile'))} nonce_present={bool(payload.get('nonce'))}", flush=True)
    if response.status != 200:
        return {"code": -1, "reason": "browser-http-error", "http_status": response.status}
    result = response.json()
    if not isinstance(result, dict):
        return {"code": -1, "reason": "browser-invalid-response"}
    result = {**result, "_browser_verification": state}
    print(f"浏览器: 官网签到响应 code={result.get('code')} reason={result.get('reason') or 'none'} repeated={result.get('repeated') is True}", flush=True)
    return result


def browser_checkin(cookie, user_agent=None):
    from playwright.sync_api import Error, TimeoutError, sync_playwright

    # Only a newly launched process with a unique empty profile can be used.
    channel = os.environ.get("GLADOS_BROWSER_CHANNEL", "chrome").strip()
    headless = os.environ.get("GLADOS_BROWSER_HEADLESS", "false").lower() == "true"
    try:
        with sync_playwright() as playwright:
            with standalone_context(playwright, channel, headless, user_agent) as context:
                context.add_cookies(parse_cookies(cookie))
                return submit_page(context)
    except TimeoutError:
        return {"code": -1, "reason": "browser-timeout",
                "message": "官网浏览器流程超时，结果不确定；请核对官网记录，不会自动再次提交。"}
    except (Error, OSError, RuntimeError, ValueError):
        # Playwright exceptions can include cookie-bearing request diagnostics.
        return {"code": -1, "reason": "browser-error"}
