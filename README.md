### 2026-11 签到接口说明

官网目前会先请求 `/api/user/checkin/challenge`，再携带 nonce、proof 和验证状态签到。
脚本使用相同的接口流程；仅当服务端没有要求 Turnstile 时才提交签到。
如果要求 Cloudflare 浏览器验证，脚本不生成或伪造验证令牌，也不自动重试签到，
会显示“需要官网验证”并返回退出码 2。此时请在官网完成签到。
本次接口适配不保证 GitHub Actions 能通过 Cloudflare；手动浏览器签到成功不等于纯 HTTP 请求可用。

运行方式：`python -m pip install -r requirements.txt`，配置 `COOKIES` 后执行 `python checkin.py`。
可选 `USER_AGENTS` 使用取得 Cookie 的浏览器的真实 User-Agent；多账号可每行一个，单行配置应用于所有账号。
Cookie 必须包含当前登录会话的完整值（例如 `gld:sess` 和 `gld:sess.sig`），不要把真实值提交到仓库或日志。

Actions 的 **Run workflow** 提供 `status_only`：勾选后只读查询，不执行签到，也不能用来证明今日已签。
手动运行默认不发送通知，按需勾选 `notify`；定时运行保持原有签到和通知行为。
`CHECKIN_STATUS_ONLY=true` 提供同等命令行只读模式。

退出码：0 表示签到成功、已签，或显式只读查询成功；1 表示请求/认证/结果异常；2 表示需要官网浏览器验证。
失败和需验证结果均保留为 Actions 失败，不会通过忽略退出码把任务变绿。

本地回归检查：`python -m unittest discover -s tests -v`。PR 的测试不读取账号 Secrets，也不访问签到接口。

### 添加**secret**

1. 跳转至自己的仓库的`Settings`->`Secrets and variables`->`Action`

2. 添加1个`repository secret`，命名为`COOKIES`，其值对应GLaDOS账号的cookie值中的有效部分（获取方式如下）

- 在GLaDOS的签到页面按`F12`

- 切换到`Network`页面下，刷新

![图片加载失败](imgs/2.png)

- 点击第一个选项卡后在`Request Headers`下找到`Cookie`，右键复制cookie的值即可

  > 参考格式：koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;

![图片加载失败](imgs/3.png)

- 多账号请在 `COOKIES` 中 添加多个 `cookies` 中间使用 `&`连接即可。（例如： `c1&c3&c3...`）

3. 手机推送（非必须）

- 添加1个`repository secret`，命名为`SENDKEY`，其值对应 PushDeer key: ([获取地址](https://www.pushdeer.com/product.html))。

### **star**自己的仓库

![图片加载失败](imgs/4.png)

## 文件结构

```shell
│  checkin.py	# 签到脚本
│
├─.github
│  └─workflows
│          gladosCheck.yml	# Actions 配置文件
```

## 声明

本项目不保证稳定运行与更新, 因GitHub相关规定可能会删库, 请注意备份
