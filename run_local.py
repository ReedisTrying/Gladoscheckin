"""Scheduled-task entry point: no console window, credentials, or browser reuse."""

import contextlib
import datetime
import json
import os
from pathlib import Path
import sys


def run():
    root = Path(__file__).resolve().parent
    logs = root / "Logs"
    logs.mkdir(exist_ok=True)
    path = logs / ("checkin-" + datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S") + ".log")
    with open(path, "w", encoding="utf-8", buffering=1) as output:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                settings = json.loads((root / "settings.json").read_text(encoding="utf-8-sig"))
                os.environ["GLADOS_BASE_URL"] = settings["base_url"]
                os.environ["GLADOS_BROWSER_PROXY"] = settings.get("proxy", "")
                sys.argv = [str(root / "local_checkin.py"), "--profile", settings["profile"],
                            "--channel", settings.get("channel", "msedge")]
                from local_checkin import main
                result = main()
                print(f"任务退出码: {result}", flush=True)
                return result
            except Exception as error:
                print(f"任务异常类型: {type(error).__name__}；未打印请求头或登录信息。", flush=True)
                return 1


if __name__ == "__main__":
    raise SystemExit(run())
