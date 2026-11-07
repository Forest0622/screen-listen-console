#!/usr/bin/env python3
"""在 CI 的 Windows 桌面上真的把控制台开起来截一张图（可选步骤，失败不影响构建）

用法：python windows/gui_shot.py <输出png>
"""
import base64
import os
import sys
import tempfile
import time
import urllib.request

os.environ.setdefault("RV_DATA_DIR", tempfile.mkdtemp(prefix="sl-shot-"))
os.environ.setdefault("RV_PORT", "6080")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

out = sys.argv[1] if len(sys.argv) > 1 else "windows-ui.png"
PORT = 6080


def pump(root, seconds: float) -> None:
    """手动跑事件循环，让 after() 定时器真正触发（截图脚本没有 mainloop）"""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.1)


def hit(url: str, user: str, pw: str) -> int:
    req = urllib.request.Request(url)
    token = base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except Exception:
        return 0


try:
    import tkinter as tk
    from PIL import ImageGrab

    from console import App, set_dpi_aware

    set_dpi_aware()
    root = tk.Tk()
    root.geometry("560x660+20+10")
    app = App(root)
    pump(root, 0.6)

    app.on_start()
    pump(root, 1.2)

    # 等到真的抓到一帧，界面上的「抓屏状态」才会变成正常
    deadline = time.time() + 20
    while time.time() < deadline:
        if hit("http://127.0.0.1:%d/status" % PORT, app.auth_user, app.auth_pass) == 200:
            break
        pump(root, 0.5)

    # 以浏览器身份打开一次查看页，让「设备访问记录」里有真实的一条
    hit("http://127.0.0.1:%d/" % PORT, app.auth_user, app.auth_pass)
    pump(root, 2.0)

    img = ImageGrab.grab()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    img.crop((x, y, x + w, y + h)).save(out)
    print("screenshot saved:", out)
    root.destroy()
except Exception as exc:
    print("screenshot skipped: %s: %s" % (type(exc).__name__, exc))

sys.exit(0)
