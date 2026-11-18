### 2026-11 签到接口说明

默认域名为用户实际使用的 `https://glados.network`，可通过 `GLADOS_BASE_URL` 选择 `https://glados.cloud` 或 `https://glados.rocks`。
默认模式使用独立 Chrome 进程打开官网签到页，让页面自行完成 challenge、验证和表单提交。
每个账号使用临时浏览器会话；不会连接你正在使用的浏览器，也不会读取或修改你的个人浏览器配置。
脚本只点击一次签到按钮，以官网真实 POST 响应判断结果；不会控制验证组件、伪造验证令牌或在结果不确定时反复提交。
GitHub Actions 使用 Windows runner 上预装的 Chrome。脚本可在本机运行，但需要安装 Chrome。

`GLADOS_BROWSER_CHANNEL` 可设为 `chrome`（默认）或 `msedge`；`GLADOS_BROWSER_HEADLESS` 默认为 `false`。
需要使用已有代理时，单独为脚本配置 `GLADOS_BROWSER_PROXY`，例如本机 HTTP 代理地址；不会修改系统或个人浏览器设置。代理地址不支持内嵌用户名密码，避免凭据暴露在进程参数中。
`CHECKIN_MODE=http` 可显式选择纯 HTTP 模式；该模式在服务端要求 Turnstile 时停止提交，返回退出码 2。
无论在哪运行，都不保证 Cloudflare 每天放行；官网返回“今日已签”只确认已有记录，不代表本次新增积分。
日志中的 `tsState` 和 `turnstile_present` 仅显示验证状态，不输出验证令牌、Cookie 或浏览器截图。

运行方式：`python -m pip install -r requirements.txt`，配置 `COOKIES` 后执行 `python checkin.py`。
可选 `USER_AGENTS` 使用取得 Cookie 的浏览器的真实 User-Agent；多账号可每行一个，单行配置应用于所有账号。
Cookie 必须包含当前登录会话的完整值（例如 `gld:sess` 和 `gld:sess.sig`），不要把真实值提交到仓库或日志。

Actions 的 **Run workflow** 提供 `status_only`：勾选后只读查询，不执行签到，也不能用来证明今日已签。
手动运行默认不发送通知，按需勾选 `notify`；定时运行保持原有签到和通知行为。
`CHECKIN_STATUS_ONLY=true` 提供同等命令行只读模式。

退出码：0 表示签到成功、已签，或显式只读查询成功；1 表示请求/认证/结果异常；2 表示需要官网浏览器验证。
失败和需验证结果均保留为 Actions 失败，不会通过忽略退出码把任务变绿。

本地回归检查：`python -m unittest discover -s tests -v`。PR 的测试不读取账号 Secrets，也不访问签到接口。

### 本机专用浏览器模式

当云端浏览器仍无法完成验证时，可在 Windows 本机运行 `python local_checkin.py --login`。
请在脚本新建的专用窗口中登录一次；脚本不会填写密码或操作人机验证组件。
登录状态只保存在专用浏览器目录（默认 `%LOCALAPPDATA%/GLaDOSCheckin/BrowserProfile`），不导出 Cookie。
之后执行 `python local_checkin.py` 会使用该专用配置完成官网正常签到；本机运行需要电脑开机和可用桌面会话。
此入口不改变 GitHub Actions 的执行环境，不等于已经部署本机定时任务。
目录带所有权标记，拒绝使用已有的个人浏览器目录；并发运行同一个专用配置会立即停止。
本机离线浏览器检查：`python -m unittest discover -s tests -p browser_smoke.py -v`，不访问真实签到接口。

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
