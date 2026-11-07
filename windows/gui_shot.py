#!/usr/bin/env python3
"""在 CI 的 Windows 桌面上真的把控制台开起来截一张图（可选步骤，失败不影响构建）

用法：python windows/gui_shot.py <输出png>
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("RV_DATA_DIR", tempfile.mkdtemp(prefix="sl-shot-"))
os.environ.setdefault("RV_PORT", "16081")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

out = sys.argv[1] if len(sys.argv) > 1 else "windows-ui.png"

try:
    import tkinter as tk
    from PIL import ImageGrab

    from console import App, set_dpi_aware

    set_dpi_aware()
    root = tk.Tk()
    root.geometry("%dx%d+30+30" % (560, 700))
    app = App(root)
    root.update()
    time.sleep(0.5)
    app.on_start()
    root.update()
    time.sleep(3.0)
    root.update()

    img = ImageGrab.grab()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    img.crop((x, y, x + w, y + h)).save(out)
    print("screenshot saved:", out)
    root.destroy()
except Exception as exc:
    print("screenshot skipped: %s: %s" % (type(exc).__name__, exc))

sys.exit(0)
