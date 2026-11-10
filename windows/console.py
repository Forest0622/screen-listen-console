#!/usr/bin/env python3
"""屏幕监听控制 · Windows 控制台

功能与 macOS 版一致：
  · 开启 / 关闭服务，显示服务与抓屏状态（不显示实时画面）
  · 列出三个访问地址（本机 / 局域网 / 计算机名），可复制、可在本机打开
  · 显示当前账号密码，可点「修改账号密码」修改或随机生成
  · 按客户端 IP 显示访问记录
"""
import json
import os
import random
import socket
import sys
import threading
import time
import webbrowser

import tkinter as tk
from tkinter import font as tkfont

import server as srv

APP_TITLE = "屏幕监听控制台 v1.3.5"
WIN_W, WIN_H = 560, 760

BG = "#1f1f1f"
CARD = "#252525"
CARD_LINE = "#3d3d3d"
TEXT = "#e6e6e6"
DIM = "#9a9a9a"
BTN = "#2f2f2f"
BTN_ACTIVE = "#3a3a3a"
GREEN = "#3ccf5f"
RED = "#e5533d"
BLUE = "#3b82f6"

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_TITLE = ("Microsoft YaHei UI", 17, "bold")
FONT_BOLD = ("Microsoft YaHei UI", 12, "bold")
FONT_MONO = ("Consolas", 10)


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def set_dpi_aware() -> None:
    try:
        import ctypes
    except Exception:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Windows 8.1+
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # Windows 7
        except Exception:
            pass


def read_config() -> dict:
    """读配置，读不到返回空 dict（避免误覆盖）"""
    try:
        with open(srv.CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        user = str(data.get("user") or srv.DEFAULT_USER)
        pw = str(data.get("password") or "")
        if not pw:
            return {}
        return {"user": user, "password": pw}
    except Exception:
        return {}


def write_config(user: str, password: str) -> None:
    srv._write_config(user, password)


def read_clients() -> list:
    try:
        with open(srv.CLIENTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.auth_user = srv.DEFAULT_USER
        self.auth_pass = ""
        self._status_result = None
        self._status_busy = False
        self._after_id = None
        self._msg = ""

        self._init_credentials()
        self._style()
        self._build()
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------ 初始化
    def _init_credentials(self) -> None:
        cfg = read_config()
        if cfg:
            self.auth_user = cfg["user"]
            self.auth_pass = cfg["password"]
        else:
            self.auth_pass = srv._random_password()
            write_config(self.auth_user, self.auth_pass)

    def _style(self) -> None:
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(WIN_W, 700)
        ico = resource_path(os.path.join("assets", "AppIcon.ico"))
        try:
            self.root.iconbitmap(ico)
        except Exception:
            pass

    def _btn(self, parent, text, command, width=14, bg=BTN):
        return tk.Button(parent, text=text, command=command, font=FONT_UI,
                         bg=bg, fg=TEXT, activebackground=BTN_ACTIVE, activeforeground=TEXT,
                         relief="flat", bd=0, width=width, height=1, cursor="hand2",
                         disabledforeground="#666666")

    # ------------------------------------------------------------ 界面
    def _build(self) -> None:
        root = self.root
        outer = tk.Frame(root, bg=BG, padx=20, pady=16)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="屏幕监听服务", font=FONT_TITLE, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(outer, text="本窗口只做启停与状态查看，不显示画面",
                 font=FONT_UI, bg=BG, fg=DIM).pack(anchor="w", pady=(4, 10))

        card = tk.Frame(outer, bg=CARD, highlightbackground=CARD_LINE,
                        highlightthickness=1, padx=14, pady=12)
        card.pack(fill="x")

        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x")
        self.dot = tk.Canvas(head, width=12, height=12, bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self.dot.create_oval(2, 2, 10, 10, fill=RED, outline=RED, tags="dot")
        self.state_label = tk.Label(head, text="服务已关闭", font=FONT_BOLD, bg=CARD, fg=TEXT)
        self.state_label.pack(side="left")

        self.sub_label = tk.Label(card, text="服务未开启，无可用地址", font=FONT_UI,
                                  bg=CARD, fg=DIM)
        self.sub_label.pack(anchor="w", pady=(8, 0))

        self.cap_label = tk.Label(outer, text="抓屏状态：未运行", font=FONT_UI, bg=BG, fg=DIM)
        self.cap_label.pack(anchor="w", pady=(10, 8))

        row1 = tk.Frame(outer, bg=BG)
        row1.pack(fill="x")
        self.btn_start = self._btn(row1, "开启服务", self.on_start, width=12)
        self.btn_start.pack(side="left")
        self.btn_stop = self._btn(row1, "关闭服务", self.on_stop, width=12)
        self.btn_stop.pack(side="left", padx=8)
        self.btn_refresh = self._btn(row1, "刷新状态", self.on_refresh, width=12, bg="#4a4a4a")
        self.btn_refresh.pack(side="right")

        tk.Label(outer, text="设备访问地址", font=FONT_BOLD, bg=BG, fg=TEXT).pack(anchor="w", pady=(14, 6))
        self.addr_rows = []
        self.addr_values = ["—"] * 5
        for i, name in enumerate(("本机", "局域网", "同域名", "账号", "密码")):
            r = tk.Frame(outer, bg=BG)
            r.pack(fill="x", pady=(0, 8))
            lbl = tk.Label(r, text="%s　　—" % name, font=FONT_MONO, bg=BG, fg="#d6d6d6",
                           anchor="w", justify="left")
            lbl.pack(side="left", fill="x", expand=True)
            btn = self._btn(r, "复制", lambda i=i: self.on_copy_row(i), width=6)
            btn.pack(side="right")
            btn.configure(state="disabled")
            self.addr_rows.append((lbl, btn))

        row2 = tk.Frame(outer, bg=BG)
        row2.pack(fill="x", pady=(10, 0))
        self._btn(row2, "复制全部", self.on_copy, width=12).pack(side="left")
        self._btn(row2, "在本机打开", self.on_open, width=12).pack(side="left", padx=8)
        self._btn(row2, "修改账号密码", self.on_edit, width=14).pack(side="right")

        tk.Label(outer, text="设备访问记录（最近在前）", font=FONT_BOLD,
                 bg=BG, fg=TEXT).pack(anchor="w", pady=(14, 6))
        box = tk.Frame(outer, bg=CARD, highlightbackground=CARD_LINE, highlightthickness=1)
        box.pack(fill="both", expand=True)
        self.rec_text = tk.Text(box, height=6, font=FONT_MONO, bg=CARD, fg="#d6d6d6",
                                relief="flat", bd=0, padx=10, pady=8, wrap="none",
                                insertbackground=TEXT)
        self.rec_text.pack(fill="both", expand=True)
        self.rec_text.configure(state="disabled")

        self.msg_label = tk.Label(outer, text="", font=FONT_UI, bg=BG, fg=DIM, anchor="w")
        self.msg_label.pack(fill="x", pady=(10, 0))

    # ------------------------------------------------------------ 状态刷新
    def refresh(self) -> None:
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        cfg = read_config()
        if cfg:
            self.auth_user = cfg["user"]
            self.auth_pass = cfg["password"]

        running = srv.is_running()
        color = GREEN if running else RED
        self.dot.itemconfigure("dot", fill=color, outline=color)
        self.state_label.configure(text="服务已开启" if running else "服务已关闭")
        self.sub_label.configure(
            text=("监听端口 %d · 抓屏正常时可远程查看" % srv.PORT) if running
            else "服务未开启，无可用地址（开启后会列出 3 个访问入口）")
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

        ip = srv.lan_ip()
        host = socket.gethostname().lower()
        if running:
            row_values = [
                "http://127.0.0.1:%d/" % srv.PORT,
                "http://%s:%d/" % (ip, srv.PORT),
                "http://%s.local:%d/" % (host, srv.PORT),
                self.auth_user,
                self.auth_pass,
            ]
        else:
            row_values = ["—"] * 5
        self.addr_values = row_values
        for (lbl, btn), name, val in zip(self.addr_rows,
                                         ("本机", "局域网", "同域名", "账号", "密码"),
                                         row_values):
            lbl.configure(text="%s　　%s" % (name, val))
            btn.configure(state="normal" if running else "disabled")

        self._update_capture_line(running)
        self._update_records()
        self.msg_label.configure(text=self._msg)

        self._after_id = self.root.after(1500, self.refresh)

    def _update_capture_line(self, running: bool) -> None:
        if not running:
            self.cap_label.configure(text="抓屏状态：未运行", fg=DIM)
            self._status_result = None
            return

        # 子线程只写结果，Tk 的控件一律在主线程（本方法）里改
        result = self._status_result
        if result is not None:
            self._status_result = None
            self._apply_capture_line(result)
        elif self.cap_label.cget("text").startswith("抓屏状态：未运行"):
            self.cap_label.configure(text="抓屏状态：正在连接…", fg=DIM)

        if self._status_busy:
            return
        self._status_busy = True

        def job():
            try:
                code, body = srv._http("http://127.0.0.1:%d/status" % srv.PORT,
                                      self.auth_user, self.auth_pass, timeout=3)
                if code == 200:
                    st = json.loads(body.decode("utf-8"))
                else:
                    st = {"ok": False, "error": "状态接口返回 %s" % code}
            except Exception as exc:
                st = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            self._status_result = st
            self._status_busy = False

        threading.Thread(target=job, daemon=True).start()

    def _apply_capture_line(self, st: dict) -> None:
        if st.get("ok"):
            age = st.get("age_sec")
            text = "抓屏状态：正常" + ("（最近一帧 %d 秒前）" % int(age) if age is not None else "")
            self.cap_label.configure(text=text, fg=GREEN)
        else:
            err = st.get("error") or "还没有拿到画面"
            self.cap_label.configure(text="抓屏状态：异常 — %s" % err, fg=RED)

    def _update_records(self) -> None:
        rows = sorted(read_clients(), key=lambda r: r.get("last", 0), reverse=True)
        lines = []
        for r in rows[:50]:
            ip = str(r.get("ip", "?"))
            tag = "本机" if ip.startswith("127.") else "外部"
            stamp = time.strftime("%H:%M:%S", time.localtime(float(r.get("last", 0))))
            lines.append("%-15s %-3s %s %d次(页%d)" % (ip, tag, stamp,
                                                      int(r.get("count", 0)),
                                                      int(r.get("pages", 0))))
        if not lines:
            lines = ["暂无访问记录"]
        self.rec_text.configure(state="normal")
        self.rec_text.delete("1.0", "end")
        self.rec_text.insert("1.0", "\n".join(lines))
        self.rec_text.configure(state="disabled")

    # ------------------------------------------------------------ 动作
    def on_start(self) -> None:
        try:
            srv.start_server()
            self._msg = "已开启服务，端口 %d" % srv.PORT
        except OSError as exc:
            self._msg = "开启失败：端口 %d 可能被占用（%s）" % (srv.PORT, exc)
        self.refresh()

    def on_stop(self) -> None:
        srv.stop_server()
        self._msg = "已关闭服务，端口 %d 已释放" % srv.PORT
        self.refresh()

    def on_refresh(self) -> None:
        self._msg = "已刷新状态"
        self.refresh()

    def on_copy(self) -> None:
        if not srv.is_running():
            self._msg = "服务未开启，没有可复制的地址"
            self.refresh()
            return
        names = ("本机", "局域网", "同域名", "账号", "密码")
        text = "\n".join("%s：%s" % (n, v)
                         for n, v in zip(names, self.addr_values))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._msg = "三条地址与账号密码已全部复制到剪贴板"
        self.refresh()

    def on_copy_row(self, idx: int) -> None:
        if not srv.is_running():
            self._msg = "服务未开启，没有可复制的内容"
            self.refresh()
            return
        names = ("本机地址", "局域网地址", "同域名地址", "账号", "密码")
        if idx < 0 or idx >= len(self.addr_values):
            return
        val = self.addr_values[idx]
        if not val or val == "—":
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(val)
        self._msg = "已复制%s：%s" % (names[idx], val)
        btn = self.addr_rows[idx][1]
        btn.configure(text="已复制")
        self.root.after(1200, lambda: btn.configure(text="复制"))
        self.refresh()

    def on_open(self) -> None:
        webbrowser.open("http://127.0.0.1:%d/" % srv.PORT)
        self._msg = "已在浏览器打开本机地址"
        self.refresh()

    def on_edit(self) -> None:
        self._edit_credentials()

    def _edit_credentials(self) -> None:
        pending_user = self.auth_user
        pending_pass = self.auth_pass
        hint = "保存后立即生效，已登录的浏览器需要重新登录。"

        win = tk.Toplevel(self.root)
        win.title("修改访问账号密码")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        body = tk.Frame(win, bg=BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="修改访问账号密码", font=FONT_BOLD, bg=BG, fg=TEXT).pack(anchor="w")
        hint_label = tk.Label(body, text=hint, font=FONT_UI, bg=BG, fg=DIM,
                              wraplength=340, justify="left")
        hint_label.pack(anchor="w", pady=(6, 12))

        form = tk.Frame(body, bg=BG)
        form.pack(fill="x")
        tk.Label(form, text="账号", font=FONT_UI, bg=BG, fg=TEXT).grid(row=0, column=0,
                                                                     sticky="w", pady=6)
        user_var = tk.StringVar(value=pending_user)
        user_entry = tk.Entry(form, textvariable=user_var, font=FONT_UI, width=26,
                              bg="#2c2c2c", fg=TEXT, insertbackground=TEXT, relief="flat")
        user_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), ipady=4)

        tk.Label(form, text="密码", font=FONT_UI, bg=BG, fg=TEXT).grid(row=1, column=0,
                                                                     sticky="w", pady=6)
        pass_var = tk.StringVar(value=pending_pass)
        pass_entry = tk.Entry(form, textvariable=pass_var, font=FONT_MONO, width=26,
                              bg="#2c2c2c", fg=TEXT, insertbackground=TEXT, relief="flat")
        pass_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), ipady=4)
        form.columnconfigure(1, weight=1)

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill="x", pady=(16, 0))

        def do_random():
            pass_var.set(srv._random_password(14))
            hint_label.configure(text="已生成随机密码，可直接保存。")

        def do_save():
            user = user_var.get().strip()
            pw = pass_var.get().strip()
            if not user or len(pw) < 6:
                hint_label.configure(text="账号不能为空，密码至少 6 位。")
                return
            self.auth_user = user
            self.auth_pass = pw
            write_config(user, pw)
            self._msg = "账号密码已保存，立即生效"
            win.destroy()
            self.refresh()

        def do_cancel():
            win.destroy()

        save = self._btn(btns, "保存", do_save, width=10, bg=BLUE)
        save.pack(side="left")
        self._btn(btns, "取消", do_cancel, width=10).pack(side="left", padx=8)
        self._btn(btns, "随机生成", do_random, width=10).pack(side="right")

        win.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - win.winfo_width()) // 2)
        y = self.root.winfo_rooty() + 120
        win.geometry("+%d+%d" % (x, y))
        user_entry.focus_set()
        win.wait_window()

    def on_close(self) -> None:
        try:
            srv.stop_server()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    set_dpi_aware()
    root = tk.Tk()
    try:
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Microsoft YaHei UI", size=10)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
