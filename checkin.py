import os
import sys
import hashlib
import time
import math
import requests
from browser_checkin import browser_checkin


# ============================================================
# GLaDOS 配置
# ============================================================

BASE_URL = "https://glados.cloud"

CHECKIN_URL = f"{BASE_URL}/api/user/checkin"
CHALLENGE_URL = f"{CHECKIN_URL}/challenge"
STATUS_URL = f"{BASE_URL}/api/user/status"

REFERER = f"{BASE_URL}/console/checkin"
ORIGIN = BASE_URL

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

CHECKIN_PAYLOAD = {
    "token": "glados.cloud"
}

TIMEOUT = 20


# ============================================================
# 工具函数
# ============================================================

def build_headers(cookie, user_agent=None):
    return {
        "Cookie": cookie,
        "Referer": REFERER,
        "Origin": ORIGIN,
        "User-Agent": user_agent or USER_AGENT,
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
    }


def safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


def mask_email(email):
    """
    避免公开 GitHub Actions 日志直接暴露完整邮箱
    """
    if not email or "@" not in email or not email.split("@", 1)[0]:
        return "未知账号"

    name, domain = email.split("@", 1)

    if len(name) <= 2:
        masked_name = name[0] + "***"
    else:
        masked_name = name[:2] + "***"

    return f"{masked_name}@{domain}"


# ============================================================
# 获取账号状态
# ============================================================

def get_account_status(session, headers):
    try:
        response = session.get(
            STATUS_URL,
            headers=headers,
            timeout=TIMEOUT
        )

    except requests.RequestException as exc:
        return None, None, "账户状态网络请求失败"

    if response.status_code != 200:
        return (
            None,
            None,
            f"账户状态接口 HTTP {response.status_code}"
        )

    result = safe_json(response)

    if not isinstance(result, dict):
        return (
            None,
            None,
            "账户状态接口没有返回有效 JSON"
        )

    data = result.get("data")

    if result.get("code") not in (0, "0") or not isinstance(data, dict):
        message = (
            result.get("message")
            or result.get("msg")
            or result.get("code")
            or "未知返回"
        )

        return (
            None,
            None,
            "账号认证失败或 Cookie 已失效，请重新登录并更新会话"
        )

    email = data.get("email") or "未知账号"

    raw_leftdays = data.get("leftDays")

    leftdays = None

    if raw_leftdays is not None:
        try:
            leftdays = int(float(raw_leftdays))
        except (TypeError, ValueError):
            pass

    return email, leftdays, None


# ============================================================
# 执行签到
# ============================================================

def classify_checkin(result):
    """Business errors take precedence over message-based success detection."""
    if not isinstance(result, dict):
        return "fail", "签到接口没有返回有效 JSON 对象", 0

    message = str(result.get("message") or result.get("msg") or "").strip()
    reason = result.get("reason")
    code = result.get("code")
    lower = message.lower()

    if reason == "turnstile" or "cloudflare verification failed" in lower:
        return "blocked", "Cloudflare 验证未通过，未记录签到；请在官网完成签到。", 0
    if reason == "device-mismatch":
        return "fail", "登录设备不匹配；请将 USER_AGENTS 设置为取得 Cookie 的浏览器 User-Agent。", 0
    if reason or code not in (0, "0", 1, "1"):
        return "fail", f"签到被拒绝 (code={code}, reason={reason or 'unknown'})", 0

    if "nothing was recorded" in lower or "failed" in lower:
        return "fail", "签到响应含失败信息，请先核对官网记录。", 0
    repeat_markers = ("checkin repeats", "please try tomorrow", "already check", "already signed")
    if result.get("repeated") is True or any(x in lower for x in repeat_markers):
        if result.get("_browser_verification") in ("timeout", "error", "unknown"):
            return "blocked", "今日已有签到记录，但本次浏览器验证未完成，尚未验证自动签到能力。", 0
        return "repeat", message or "今日已签到", 0
    if code not in (0, "0"):
        return "fail", f"签到被拒绝 (code={code})", 0

    # Only a successful business code can authorize a success result.
    points = result.get("points") or 0
    return "success", message or "签到成功", points


def do_checkin(session, headers):
    """Follow the official challenge protocol; never fake a Turnstile token."""
    try:
        response = session.get(CHALLENGE_URL, headers=headers, timeout=TIMEOUT)
    except requests.RequestException:
        return "fail", "签到 challenge 网络请求失败，未提交签到。", 0
    if response.status_code != 200:
        return "fail", f"签到 challenge 接口 HTTP {response.status_code}，未提交签到。", 0
    challenge = safe_json(response)
    if not isinstance(challenge, dict):
        return "fail", "签到 challenge 未返回有效 JSON 对象，未提交签到。", 0
    if challenge.get("reason") == "turnstile":
        return "blocked", "Cloudflare 验证未通过，未提交签到，请在官网完成签到。", 0
    if challenge.get("code") not in (0, "0"):
        return "fail", f"签到 challenge 被拒绝 (code={challenge.get('code')})，请检查登录会话。", 0

    # A configured widget must be completed on the official site. Requests cannot
    # produce its token. Do not post an empty token, retry, or pretend success.
    if challenge.get("turnstile"):
        return "blocked", "官网要求 Cloudflare 浏览器验证；纯 HTTP 模式未提交签到，请在官网完成签到。", 0
    nonce = challenge.get("nonce")
    try:
        ttl = float(challenge.get("ttl"))
    except (TypeError, ValueError):
        ttl = 0
    if not isinstance(nonce, str) or not nonce or not math.isfinite(ttl) or ttl <= 2.5:
        return "fail", "签到 challenge 缺少有效 nonce/ttl，未提交签到。", 0

    payload = {
        **CHECKIN_PAYLOAD,
        "nonce": nonce,
        "proof": hashlib.sha256((nonce + ".glados-observe-v1").encode()).hexdigest(),
        "tsState": "off",  # Only used when the server has NOT requested Turnstile.
    }
    # The official page enforces this minimum interval after obtaining a nonce.
    time.sleep(2.5)
    try:
        response = session.post(CHECKIN_URL, headers=headers, json=payload, timeout=TIMEOUT)
    except requests.RequestException:
        return "fail", "签到请求结果不确定，请先核对官网记录；不会自动重复提交。", 0
    if response.status_code != 200:
        return "fail", f"签到接口 HTTP {response.status_code}，请先核对官网记录。", 0
    return classify_checkin(safe_json(response))


# ============================================================
# 单账号
# ============================================================

def process_account(cookie, index, user_agent=None, status_only=False):
    headers = build_headers(cookie, user_agent)

    with requests.Session() as session:

        if status_only:
            result_type, check_message, points = "status", "仅查询账户状态，未执行签到", 0
        elif os.environ.get("CHECKIN_MODE", "browser") == "http":
            result_type, check_message, points = do_checkin(session, headers)
        else:
            result_type, check_message, points = classify_checkin(browser_checkin(cookie, user_agent))

        email, leftdays, status_error = get_account_status(
            session,
            headers
        )

    display_email = mask_email(email)

    print("")
    print("=" * 60)
    print(f"账号 {index}: {display_email}")
    print(f"GLaDOS 返回: {check_message}")

    if leftdays is not None:
        print(f"剩余天数: {leftdays} 天")
    else:
        print("剩余天数: 获取失败")

    # --------------------------------------------------------
    # 如果签到接口正常，但状态接口失败，则仍视为真正异常
    # --------------------------------------------------------

    if status_error:
        print(f"状态检查: {status_error}")

        # Cookie 权限问题应该明确判为失败
        if email is None:
            result_type = "fail"

    # --------------------------------------------------------
    # 输出用户容易理解的结果
    # --------------------------------------------------------

    if result_type == "success":

        if points:
            status_text = f"签到成功，会员点数 +{points}"
        else:
            status_text = "签到成功"

        print(f"结果: {status_text}")

    elif result_type == "repeat":

        status_text = "今日签到已记录，无需重复签到"

        print(f"结果: {status_text}")

    elif result_type in ("blocked", "status"):
        status_text = check_message
        print(f"结果: {status_text}")
    else:
        status_text = status_error or check_message
        print(f"结果: 签到失败 - {status_text}")

    # --------------------------------------------------------
    # PushDeer 内容
    # --------------------------------------------------------

    if leftdays is not None:
        day_text = f"{leftdays} 天"
    else:
        day_text = "获取失败"

    context = (
        f"账号: {display_email}\n"
        f"状态: {status_text}\n"
        f"积分变化: {points}\n"
        f"剩余: {day_text}"
    )

    return result_type, context


# ============================================================
# PushDeer
# ============================================================

def pushdeer_send(sendkey, title, content):
    """
    直接调用 PushDeer API，不再依赖 pypushdeer Python 包。
    """

    if not sendkey:
        print("")
        print("未配置 SENDKEY，跳过 PushDeer 推送")
        return True

    url = "https://api2.pushdeer.com/message/push"

    payload = {
        "pushkey": sendkey,
        "text": title,
        "desp": content,
        "type": "text"
    }

    try:
        response = requests.post(
            url,
            data=payload,
            timeout=TIMEOUT
        )

    except requests.RequestException as exc:
        print("PushDeer 推送网络请求失败")
        return False

    if response.status_code != 200:
        print(
            f"PushDeer 推送失败，HTTP "
            f"{response.status_code}"
        )
        return False

    result = safe_json(response)

    if isinstance(result, dict):

        # PushDeer 正常通常 errno == 0
        errno = result.get("errno")

        if errno not in (None, 0, "0"):
            print(
                "PushDeer 推送失败: "
                + f"errno={errno}"
            )
            return False

    print("PushDeer 推送完成")
    return True


# ============================================================
# 主程序
# ============================================================

def main():

    print("=" * 60)
    print("GLaDOS Auto Checkin")
    print(f"API: {BASE_URL}")
    print("=" * 60)

    # --------------------------------------------------------
    # Cookie
    # --------------------------------------------------------

    raw_cookies = os.environ.get("COOKIES", "").strip()

    if not raw_cookies:

        print("未找到 GitHub Secret: COOKIES")
        return 1

    # 保持兼容原项目：
    #
    # 单账号：
    # gld:sess=xxx; sess.sig=xxx
    #
    # 多账号：
    # cookie1&cookie2
    #
    cookies = [
        item.strip()
        for item in raw_cookies.split("&")
        if item.strip()
    ]

    print(f"检测到 {len(cookies)} 个账号")

    if not cookies:
        print("COOKIES 没有有效账号")
        return 1
    status_only = os.environ.get("CHECKIN_STATUS_ONLY", "").lower() in ("true", "1", "yes")
    # One line per account; a single configured UA can be shared by all accounts.
    user_agents = os.environ.get("USER_AGENTS", "").strip().splitlines()
    if len(user_agents) not in (0, 1, len(cookies)):
        print("USER_AGENTS 须为单行，或每个账号各一行")
        return 1
    success = 0
    repeat = 0
    fail = 0
    blocked = 0
    status_count = 0

    contexts = []

    # --------------------------------------------------------
    # 逐账号执行
    # --------------------------------------------------------

    for index, cookie in enumerate(cookies, start=1):

        try:

            result_type, context = process_account(
                cookie,
                index,
                user_agents[0 if len(user_agents) == 1 else index - 1] if user_agents else None,
                status_only,
            )

        except Exception as exc:

            # 防止一个账号异常影响后续账号
            result_type = "fail"

            context = (
                f"账号 {index}\n"
                f"状态: 程序执行异常\n"
                f"异常类型: {type(exc).__name__}"
            )

            print("")
            print(
                f"账号 {index} 程序执行异常: "
                f"{type(exc).__name__}"
            )

        contexts.append(context)

        if result_type == "success":
            success += 1

        elif result_type == "repeat":
            repeat += 1

        elif result_type == "blocked":
            blocked += 1
        elif result_type == "status":
            status_count += 1
        else:
            fail += 1

    # --------------------------------------------------------
    # 总结
    # --------------------------------------------------------

    print("")
    print("=" * 60)
    print("执行结果")
    print("=" * 60)

    print(f"签到成功: {success}")
    print(f"今日已签: {repeat}")
    print(f"签到失败: {fail}")
    print(f"需要官网验证: {blocked}")
    print(f"仅查询状态: {status_count}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write(f"### GLaDOS 运行结果\n成功 {success} / 已签 {repeat} / 失败 {fail} / 需官网验证 {blocked} / 只读查询 {status_count}\n")
            if blocked:
                output.write("Cloudflare 要求浏览器验证，未记录签到；请在官网完成。只读查询不代表已签到。\n")

    title = (
        f"GLaDOS：成功{success}，"
        f"已签{repeat}，失败{fail}，需验证{blocked}，只读{status_count}"
    )

    context = "\n\n".join(contexts)

    # --------------------------------------------------------
    # 推送
    # --------------------------------------------------------

    sendkey = os.environ.get("SENDKEY", "").strip()

    pushdeer_send(
        sendkey,
        title,
        context
    )

    # --------------------------------------------------------
    # GitHub Actions 返回状态
    #
    # 成功或已经签到：
    #   exit 0 -> GitHub 绿色
    #
    # 真正失败：
    #   exit 1 -> GitHub 红色
    # --------------------------------------------------------

    if fail > 0:
        print("")
        print("存在真正的签到失败，返回退出码 1。")
        return 1

    print("")
    if blocked:
        print("需要在官网完成浏览器验证，返回退出码 2；不视为签到成功。")
        return 2
    print("所有账号状态查询正常。" if status_only else "所有账号签到状态正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
