# 屏幕监听控制（Screen Listen Console）

在同一个局域网里，用浏览器**只读查看**一台 Mac 当前屏幕的小工具。

App 本身是一个轻量控制台：只负责开关服务、显示状态、给出访问地址、记录谁访问过——**不显示实时画面**，也不提供鼠标键盘控制。

![platform](https://img.shields.io/badge/platform-macOS%2011%2B-lightgrey)
![python](https://img.shields.io/badge/runtime-Python%203-blue)
[![build](https://github.com/Forest0622/screen-listen-console/actions/workflows/build.yml/badge.svg)](https://github.com/Forest0622/screen-listen-console/actions/workflows/build.yml)

[English README](README.en.md)

## 界面截图

| 主界面 | 修改账号密码 |
|---|---|
| ![主界面](docs/images/ui-main.png) | ![修改账号密码](docs/images/ui-password.png) |

> 截图中的地址与密码已换成演示值（`192.168.1.23`、`demo-mac.local`、`Demo-Pass-2f9K`），不是真实网络信息。

## 它长什么样

- 状态框：服务开启 / 关闭、监听端口、抓屏是否正常（带最近一帧的时间）
- 一排按钮：开启服务 / 关闭服务 / 刷新状态
- 访问地址：本机 `127.0.0.1`、局域网 IP、`.local` 主机名三种，可一键复制或用本机浏览器打开，地址下方直接显示当前账号密码
- 「修改账号密码」：弹出输入框改账号密码，也可以点「随机生成」换一个 14 位强随机密码，保存即生效
- 访问记录：按客户端 IP 累计首次/最近访问时间、访问次数、打开过的页面

## 账号密码

- **第一次运行自动生成 12 位随机密码**（字符集去掉了容易看混的 `l` `I` `0` `O`），写入 `~/.remote-view/config.json`，权限 `600`；同时在 `~/.remote-view/logs/service.log` 里打印一行，忘了可以去看
- 换密码有两种办法，都不用重启服务：
  - App 里点「修改账号密码」
  - 直接编辑 `~/.remote-view/config.json`（`{"user": "admin", "password": "…"}`）
- 服务端每次请求都比对文件 `mtime`，文件一变立刻生效；客户端每 1.5 秒重读一次，界面上显示的账号密码会跟着变
- 密码长度要求 ≥ 6 位，账号不能为空

## 工作原理

一句话：**定时截图 + 网页轮询**，没有用系统自带的屏幕共享，也没有用 VNC。

```
screencapture -x -t jpg  →  sips 压到 1600px 宽 / 质量 55
        ↓ 每 1 秒
  内存里保留最新一帧  →  HTTP 服务（端口 6080，Basic 认证）
        ↓
  浏览器 /            → 带工具栏的查看页（暂停、缩放、全屏）
  浏览器 /frame.jpg   → 最新一帧
  浏览器 /status      → JSON 状态
```

- 抓屏线程空闲时降频（2 秒一帧），有请求时 1 秒一帧
- 抓屏失败按指数退避（最短 2 秒，最长 60 秒；权限类至少 30 秒），避免失败时连环弹系统授权框
- `/status` 的 `ok` 不只看有无旧图，还要求 20 秒内抓到过新帧，避免"报正常但其实缺权限"
- 访问记录按 IP 累计写入 `clients.json`（原子替换 + 3 秒节流），页面级明细写 `access.log`

## 环境要求

- macOS 11 及以上
- Python 3（macOS 装了命令行工具就有；没有就 `xcode-select --install`）
- 需要给 App 授予「屏幕录制」权限（**每台机器一次**）

## 快速开始

```bash
git clone https://github.com/Forest0622/screen-listen-console.git
cd screen-listen-console
./make-app.sh            # 产出 dist/屏幕监听控制.app
open "dist/屏幕监听控制.app"
```

1. 点「开启服务」
2. 首次会要求「屏幕录制」权限：系统设置 → 隐私与安全性 → 录屏与系统录音 → 添加并打开开关 → `⌘Q` 退出 App 再重新打开
3. 看到「抓屏状态：正常」即可
4. 窗口「设备访问地址」下方就是本次生成的账号密码，同一局域网的其他设备用它登录浏览

## 打包成安装包

```bash
./make-dmg.sh            # 产出 dist/屏幕监听控制-安装包.dmg
```

DMG 内含 App、一个指向「应用程序」的软链和一份使用说明，拖进去即可安装。

分发到别人的 Mac 时有两件必然会发生的事，不是 bug：

- **首次打开被 Gatekeeper 拦**：本项目的默认签名是本机自签 / ad-hoc，没有 Apple 公证。右键点 App →「打开」→ 再点一次「打开」。
- **对方必须自己授权一次「屏幕录制」**：TCC 权限按机器授予，无法随包携带。

## 自动构建

`.github/workflows/build.yml` 在每次 push / PR 时于 GitHub 的 macOS runner 上编译 App、打 DMG 并上传产物；推一个 `v*` 标签时自动创建 Release 并附上 DMG。

## 自定义

| 想改什么 | 改哪里 |
|---|---|
| 账号密码 | App 里点「修改账号密码」，或改 `~/.remote-view/config.json` |
| 端口 | `server.py` 的 `PORT`（也支持 `RV_PORT` 环境变量）；同时改 `Console.swift` 里的 `PORT` |
| 画质 / 宽度 | `server.py` 的 `TARGET_WIDTH`、`INTERVAL` |
| 数据目录 | 默认 `~/.remote-view`，可用 `RV_DATA_DIR` 覆盖 |

## 已知限制（都是实测结论，不是偷懒）

- **macOS 的系统「屏幕共享」接不进 noVNC**：它只提供 Apple 私有认证（`RFB 003.889`，安全类型 `30/33/36/35`），没有经典 VNC 的密码类型 2，所以第三方 VNC 客户端在握手阶段就被挡下。这就是本项目改用"截图 + 网页"的原因。
- **不能用 launchd 常驻或开机自启**：`launchd`（gui 域）启动的进程拿不到「屏幕录制」权限，抓屏必然失败，且用户无法在设置里单独给它授权。所以本工具只能手动打开 App 再点开启。
- **仅限局域网**：没有做内网穿透或反向代理。要在公网访问，请自己套 VPN / Tailscale / 反代，并务必换掉密码。
- **只读**：不提供键鼠控制，不传输剪贴板。

## 安全提示

- HTTP Basic 认证在局域网内是**明文**传输的，不要在公共 Wi-Fi 上开
- 服务监听 `0.0.0.0:6080`，同网段任何人只要能连上端口就能看到登录框；密码一旦泄露等于屏幕被看
- 密码首次运行随机生成，不再是硬编码的固定值；但 App 界面和配置文件会明文显示它，截图/分享界面时注意打码
- 访问日志包含客户端 IP，属于隐私数据，别提交进仓库（仓库已通过 `.gitignore` 排除）

## 目录结构

```
server.py                 截图服务（Python 标准库，零依赖）
Console.swift             控制台（AppKit 手写布局，swiftc 直接编译）
make-app.sh               编译并组装 .app
make-dmg.sh               打包 DMG 安装盘
assets/AppIcon.icns       图标
docs/使用说明.txt          随安装包分发的说明
docs/images/              界面截图
.github/workflows/        自动构建与发布
```

## License

MIT
