import os
import sys
import requests


# ============================================================
# GLaDOS 配置
# ============================================================

BASE_URL = "https://glados.cloud"

CHECKIN_URL = f"{BASE_URL}/api/user/checkin"
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

def build_headers(cookie):
    return {
        "Cookie": cookie,
        "Referer": REFERER,
        "Origin": ORIGIN,
        "User-Agent": USER_AGENT,
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
    if not email or "@" not in email:
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
        return None, None, f"账户状态网络请求失败: {exc}"

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

    if not isinstance(data, dict):
        message = (
            result.get("message")
            or result.get("msg")
            or result.get("code")
            or "未知返回"
        )

        return (
            None,
            None,
            f"账号认证失败或 Cookie 已失效: {message}"
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

def do_checkin(session, headers):
    """
    返回:
        success  = 本次签到成功
        repeat   = 今天已经签到 / 今日记录已经存在
        fail     = 真正失败
    """

    try:
        response = session.post(
            CHECKIN_URL,
            headers=headers,
            json=CHECKIN_PAYLOAD,
            timeout=TIMEOUT
        )

    except requests.RequestException as exc:
        return "fail", f"签到网络请求失败: {exc}", 0

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
            "签到接口没有返回有效 JSON",
            0
        )

    message = str(
        result.get("message")
        or result.get("msg")
        or ""
    ).strip()

    points = result.get("points", 0)

    if points is None:
        points = 0

    message_lower = message.lower()

    # --------------------------------------------------------
    # 当前 GLaDOS 的正常“已经记录 / 今天已经签过”返回
    # --------------------------------------------------------

    repeat_markers = (
        "today's observation logged",
        "return tomorrow",
        "checkin repeats",
        "please try tomorrow",
        "already check",
        "already signed",
        "repeats",
    )

    if any(marker in message_lower for marker in repeat_markers):
        return "repeat", message, points

    # --------------------------------------------------------
    # 正常签到成功
    # --------------------------------------------------------

    success_markers = (
        "checkin! got",
        "checkin success",
        "checkin successful",
        "successfully checked",
    )

    if any(marker in message_lower for marker in success_markers):
        return "success", message, points

    # 历史版本中 code == 0 通常代表成功
    code = result.get("code")

    if code == 0 or code == "0":
        return "success", message or "签到成功", points

    # --------------------------------------------------------
    # 权限 / Cookie 问题
    # --------------------------------------------------------

    auth_fail_markers = (
        "没有权限",
        "unauthorized",
        "not authorized",
        "forbidden",
        "permission",
        "login",
    )

    if any(marker in message_lower for marker in auth_fail_markers):
        return (
            "fail",
            f"账号认证失败，可能 Cookie 已失效: {message}",
            points
        )

    # --------------------------------------------------------
    # 其他未知结果
    # --------------------------------------------------------

    if not message:
        return (
            "fail",
            f"签到接口返回未知结果: {result}",
            points
        )

    return "fail", f"未知签到结果: {message}", points


# ============================================================
# 单账号
# ============================================================

def process_account(cookie, index):
    headers = build_headers(cookie)

    with requests.Session() as session:

        result_type, check_message, points = do_checkin(
            session,
            headers
        )

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

    else:

        status_text = check_message

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
        print(f"PushDeer 推送失败: {exc}")
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
                + str(result.get("error") or result)
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

    success = 0
    repeat = 0
    fail = 0

    contexts = []

    # --------------------------------------------------------
    # 逐账号执行
    # --------------------------------------------------------

    for index, cookie in enumerate(cookies, start=1):

        try:

            result_type, context = process_account(
                cookie,
                index
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
                f"{type(exc).__name__}: {exc}"
            )

        contexts.append(context)

        if result_type == "success":
            success += 1

        elif result_type == "repeat":
            repeat += 1

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

    title = (
        f"GLaDOS：成功{success}，"
        f"已签{repeat}，失败{fail}"
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
    print("所有账号签到状态正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
