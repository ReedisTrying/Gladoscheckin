import os
import requests

from pypushdeer import PushDeer


# -------------------------------------------------------------------------------------------
# GLaDOS 配置
# -------------------------------------------------------------------------------------------

BASE_URL = "https://glados.cloud"
CHECK_IN_URL = f"{BASE_URL}/api/user/checkin"
STATUS_URL = f"{BASE_URL}/api/user/status"

REFERER = f"{BASE_URL}/console/checkin"
ORIGIN = BASE_URL

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

# 2026 年 GLaDOS 已将签到 token 从 glados.one 改为 glados.cloud
PAYLOAD = {
    "token": "glados.cloud"
}

TIMEOUT = 20


def build_headers(cookie):
    """构造请求头"""
    return {
        "cookie": cookie,
        "referer": REFERER,
        "origin": ORIGIN,
        "user-agent": USER_AGENT,
        "content-type": "application/json;charset=UTF-8",
        "accept": "application/json, text/plain, */*",
    }


def safe_json(response):
    """安全解析 JSON，失败时返回 None"""
    try:
        return response.json()
    except Exception:
        return None


def get_account_status(session, headers):
    """
    获取账号状态。

    返回:
        email, leftdays, error_message
    """

    try:
        response = session.get(
            STATUS_URL,
            headers=headers,
            timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        return "未知账号", None, f"账户状态请求失败: {exc}"

    if response.status_code != 200:
        return (
            "未知账号",
            None,
            f"账户状态 HTTP {response.status_code}"
        )

    result = safe_json(response)

    if not isinstance(result, dict):
        return (
            "未知账号",
            None,
            "账户状态接口返回的不是有效 JSON"
        )

    data = result.get("data")

    if not isinstance(data, dict):
        # 常见原因：Cookie 已失效
        message = result.get("message") or result.get("code") or str(result)

        return (
            "未知账号",
            None,
            f"账户状态异常，可能 Cookie 已失效: {message}"
        )

    email = data.get("email") or "未知账号"

    raw_leftdays = data.get("leftDays")

    leftdays = None

    if raw_leftdays is not None:
        try:
            leftdays = int(float(raw_leftdays))
        except (TypeError, ValueError):
            leftdays = None

    return email, leftdays, None


def do_checkin(session, headers):
    """
    执行签到。

    返回:
        result_type:
            success = 签到成功
            repeat  = 今日已经签到
            fail    = 签到失败

        message
        points
    """

    try:
        response = session.post(
            CHECK_IN_URL,
            headers=headers,
            json=PAYLOAD,
            timeout=TIMEOUT
        )

    except requests.RequestException as exc:
        return "fail", f"签到请求失败: {exc}", 0

    if response.status_code != 200:
        return (
            "fail",
            f"签到接口 HTTP {response.status_code}",
            0
        )

    result = safe_json(response)

    if not isinstance(result, dict):
        return (
            "fail",
            f"签到接口未返回有效 JSON: {response.text[:200]}",
            0
        )

    message = str(result.get("message") or "")
    points = result.get("points", 0)

    if points is None:
        points = 0

    message_lower = message.lower()

    # 已签到
    if (
        "checkin repeats" in message_lower
        or "please try tomorrow" in message_lower
        or "repeats" in message_lower
    ):
        return "repeat", message, points

    # 签到成功
    if (
        "checkin!" in message_lower
        or "checkin success" in message_lower
        or "checkin success" in message_lower
    ):
        return "success", message, points

    # 明确出现旧接口提示
    if "please checkin via" in message_lower:
        return (
            "fail",
            f"{message}；GLaDOS 接口可能再次发生变化",
            points
        )

    # 没有 message
    if not message:
        return (
            "fail",
            f"签到接口返回异常: {result}",
            points
        )

    # 其他未知返回
    return "fail", message, points


def process_account(cookie, index):
    """处理单个 GLaDOS 账号"""

    headers = build_headers(cookie)

    with requests.Session() as session:

        # 先执行签到
        result_type, check_message, points = do_checkin(
            session,
            headers
        )

        # 再获取账户状态
        email, leftdays, status_error = get_account_status(
            session,
            headers
        )

    print("")
    print("=" * 60)
    print(f"账号 {index}: {email}")
    print(f"签到接口返回: {check_message}")

    if leftdays is not None:
        print(f"剩余天数: {leftdays}")
    else:
        print("剩余天数: 获取失败")

    if status_error:
        print(status_error)

    if result_type == "success":

        if points:
            message_status = f"签到成功，会员点数 +{points}"
        else:
            message_status = "签到成功"

    elif result_type == "repeat":

        message_status = "今日已经签到，明天再来"

    else:

        message_status = f"签到失败：{check_message}"

    if leftdays is not None:
        message_days = f"{leftdays} 天"
    else:
        message_days = "获取失败"

    account_context = (
        f"账号: {email}\n"
        f"状态: {message_status}\n"
        f"P: {points}\n"
        f"剩余: {message_days}"
    )

    if status_error:
        account_context += f"\n账户状态: {status_error}"

    return (
        result_type,
        account_context
    )


# -------------------------------------------------------------------------------------------
# GitHub Actions
# -------------------------------------------------------------------------------------------

if __name__ == "__main__":

    # PushDeer key
    # GitHub Secret 名称：SENDKEY
    sckey = os.environ.get("SENDKEY", "").strip()

    # GLaDOS Cookie
    # GitHub Secret 名称：COOKIES
    #
    # 单账号:
    # koa:sess=xxxx; koa:sess.sig=xxxx
    #
    # 多账号:
    # cookie1&cookie2&cookie3

    cookie_env = os.environ.get("COOKIES", "")

    cookies = [
        cookie.strip()
        for cookie in cookie_env.split("&")
        if cookie.strip()
    ]

    success = 0
    fail = 0
    repeats = 0

    contexts = []

    if not cookies:

        title = "Glados - 未找到 Cookies"
        context = (
            "未检测到 GitHub Secret: COOKIES\n"
            "请进入 Settings → Secrets and variables → Actions "
            "检查 COOKIES。"
        )

        print(context)

    else:

        print(f"共检测到 {len(cookies)} 个 GLaDOS 账号")
        print(f"API: {BASE_URL}")

        for index, cookie in enumerate(cookies, start=1):

            try:

                result_type, account_context = process_account(
                    cookie,
                    index
                )

                contexts.append(account_context)

                if result_type == "success":
                    success += 1

                elif result_type == "repeat":
                    repeats += 1

                else:
                    fail += 1

            except Exception as exc:

                # 防止一个账号异常导致其他账号完全无法执行

                fail += 1

                error_context = (
                    f"账号 {index}: 执行异常\n"
                    f"错误: {type(exc).__name__}: {exc}"
                )

                contexts.append(error_context)

                print("")
                print(error_context)

        title = (
            f"Glados, 成功{success}, "
            f"失败{fail}, 重复{repeats}"
        )

        context = "\n\n".join(contexts)

    print("")
    print("=" * 60)
    print(title)
    print("=" * 60)
    print(context)

    # ---------------------------------------------------------------------------------------
    # PushDeer 推送
    # ---------------------------------------------------------------------------------------

    if not sckey:

        print("")
        print("未配置 SENDKEY，不进行 PushDeer 推送")

    else:

        try:

            pushdeer = PushDeer(
                pushkey=sckey
            )

            pushdeer.send_text(
                title,
                desp=context
            )

            print("")
            print("PushDeer 推送完成")

        except Exception as exc:

            print("")
            print(
                "PushDeer 推送失败:",
                f"{type(exc).__name__}: {exc}"
            )
