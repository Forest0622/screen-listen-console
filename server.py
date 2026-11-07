#!/usr/bin/env python3
"""本地网页远程看屏服务：定时截屏 -> 浏览器实时查看（独立端口，带 HTTP Basic 认证）"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = int(os.environ.get("RV_PORT", "6080"))
USER = "admin"
PASSWORD = "2010622"          # 访问密码
FRAME_DIR = "/tmp/remoteview"
TARGET_WIDTH = 1600
INTERVAL = 1.0                    # 秒/帧
IDLE_SLEEP = 2.0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据目录：优先取 RV_DATA_DIR（App 会传 ~/.remote-view），否则与脚本同级
DATA_DIR = os.environ.get("RV_DATA_DIR") or BASE_DIR
LOG_DIR = os.path.join(DATA_DIR, "logs")
CLIENTS_FILE = os.path.join(LOG_DIR, "clients.json")
ACCESS_LOG = os.path.join(LOG_DIR, "access.log")

_clients_lock = threading.Lock()
_clients: dict = {}
_last_dump = 0.0


def _dump_clients(force: bool = False) -> None:
    """把访问记录落盘，供桌面控制台读取"""
    global _last_dump
    with _clients_lock:
        now = time.time()
        if not force and now - _last_dump < 3.0:
            return
        _last_dump = now
        snapshot = [dict(v) for v in _clients.values()]
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        tmp = CLIENTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        os.replace(tmp, CLIENTS_FILE)
    except Exception:
        pass


def record_visit(ip: str, path: str) -> None:
    now = time.time()
    with _clients_lock:
        rec = _clients.get(ip)
        if rec is None:
            rec = {"ip": ip, "first": now, "last": now, "count": 0, "pages": 0}
            _clients[ip] = rec
        rec["last"] = now
        rec["count"] += 1
        is_page = path in ("/", "/index.html")
        if is_page:
            rec["pages"] += 1
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    if is_page:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(ACCESS_LOG, "a", encoding="utf-8") as f:
                f.write(f"{stamp}\t{ip}\t打开页面\n")
        except Exception:
            pass
    _dump_clients(force=is_page)


_state = {"jpeg": None, "ts": 0.0, "error": None, "last_fetch": 0.0,
          "fails": 0, "need_permission": False}
_lock = threading.Lock()

HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>远程看屏</title>
<style>
 html,body{margin:0;height:100%;background:#111;color:#ddd;font:14px -apple-system,Helvetica,sans-serif}
 #bar{position:fixed;top:0;left:0;right:0;height:38px;display:flex;align-items:center;gap:12px;
      padding:0 12px;background:#1b1b1b;border-bottom:1px solid #333;z-index:5;font-size:13px}
 #view{position:absolute;top:38px;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;overflow:hidden}
 img{max-width:100%;max-height:100%;object-fit:contain;cursor:zoom-in;transition:transform .15s}
 img.zoom{transform:scale(1.6);cursor:zoom-out}
 .dot{width:8px;height:8px;border-radius:50%;background:#3c3;display:inline-block}
 #err{position:absolute;bottom:10px;left:12px;color:#f66}
 button{background:#2b2b2b;color:#ddd;border:1px solid #444;border-radius:6px;padding:4px 10px;cursor:pointer}
</style></head>
<body>
<div id="bar">
  <span class="dot" id="dot"></span><span id="stat">连接中…</span>
  <span style="margin-left:auto" id="ts"></span>
  <button onclick="toggleZoom()">缩放</button>
  <button onclick="togglePause()" id="pbtn">暂停</button>
  <button onclick="document.documentElement.requestFullscreen()">全屏</button>
</div>
<div id="view"><img id="img" alt="屏幕画面"></div>
<div id="err"></div>
<script>
let paused=false, zoom=false, miss=0;
const img=document.getElementById('img');
function togglePause(){paused=!paused;document.getElementById('pbtn').textContent=paused?'继续':'暂停';}
function toggleZoom(){zoom=!zoom;img.classList.toggle('zoom',zoom);}
function tick(){
  if(paused) return setTimeout(tick,1000);
  const t=Date.now();
  const next=new Image();
  next.onload=()=>{
    img.src=next.src; miss=0;
    document.getElementById('stat').textContent='画面已连接';
    document.getElementById('err').textContent='';
    document.getElementById('ts').textContent=new Date().toLocaleTimeString();
    setTimeout(tick, Math.max(300, 1000-(Date.now()-t)));
  };
  next.onerror=()=>{
    miss++;
    document.getElementById('stat').textContent='重连中…('+miss+')';
    document.getElementById('err').textContent='取帧失败，将自动重试';
    setTimeout(tick,2000);
  };
  next.src='/frame.jpg?t='+t;
}
tick();
</script></body></html>
"""


def capture_once() -> None:
    os.makedirs(FRAME_DIR, exist_ok=True)
    raw = os.path.join(FRAME_DIR, "raw.jpg")
    small = os.path.join(FRAME_DIR, "frame.jpg")
    try:
        try:
            os.remove(raw)          # 先清掉旧帧，才能判断本次是否真的抓到了屏
        except OSError:
            pass
        subprocess.run(["/usr/sbin/screencapture", "-x", "-t", "jpg", raw],
                       check=True, timeout=10, capture_output=True)
        subprocess.run(["/usr/bin/sips", "-Z", str(TARGET_WIDTH),
                        "--setProperty", "format", "jpeg",
                        "--setProperty", "formatOptions", "55",
                        raw, "--out", small],
                       check=True, timeout=15, capture_output=True)
        with open(small, "rb") as f:
            data = f.read()
        with _lock:
            _state["jpeg"] = data
            _state["ts"] = time.time()
            _state["error"] = None
            _state["fails"] = 0
            _state["need_permission"] = False
    except Exception as exc:  # 截屏权限或临时失败
        perm = isinstance(exc, subprocess.CalledProcessError) and not os.path.exists(raw)
        with _lock:
            _state["fails"] = _state.get("fails", 0) + 1
            if perm:
                _state["need_permission"] = True
                _state["error"] = ("需要屏幕录制权限：系统设置 → 隐私与安全性 → 录屏与系统录音，"
                                   "打开「屏幕监听控制」后重启 App")
            else:
                _state["error"] = f"{type(exc).__name__}: {exc}"


def worker() -> None:
    """抓屏循环：无人访问时降频但不停摆；失败后退避，绝不每秒重试刷授权弹窗"""
    while True:
        idle = False
        try:
            with _lock:
                idle = (time.time() - _state["last_fetch"]) > 30
            capture_once()
        except Exception as exc:  # 兜底：连目录创建等异常也不终止线程
            with _lock:
                _state["error"] = f"{type(exc).__name__}: {exc}"
        with _lock:
            fails = _state.get("fails", 0)
            need_perm = _state.get("need_permission", False)
        if fails:
            delay = min(60.0, float(2 ** min(fails, 6)))
            if need_perm:
                delay = max(delay, 30.0)   # 权限问题：至少 30 秒才重试一次
        else:
            delay = IDLE_SLEEP if idle else INTERVAL
        time.sleep(delay)


class Handler(BaseHTTPRequestHandler):
    server_version = "RemoteView/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 降低日志噪音
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def _auth_ok(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:]).decode("utf-8", "replace")
        except Exception:
            return False
        user, _, pw = raw.partition(":")
        return user == USER and pw == PASSWORD

    def _require_auth(self) -> bool:
        if self._auth_ok():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="remote-view"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        if not self._auth_ok():
            self._require_auth()
            return
        path = self.path.split("?")[0]
        record_visit(self.client_address[0], path)
        if path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/frame.jpg":
            with _lock:
                _state["last_fetch"] = time.time()
                jpeg, ts, err = _state["jpeg"], _state["ts"], _state["error"]
            if jpeg is None:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Time", f"{ts:.3f}")
            self.end_headers()
            self.wfile.write(jpeg)
            return
        if path == "/status":
            with _lock:
                fresh = bool(_state["ts"]) and (time.time() - _state["ts"]) < 20
                payload = {"ok": bool(_state["error"] is None and fresh),
                           "age_sec": round(time.time() - _state["ts"], 2) if _state["ts"] else None,
                           "error": _state["error"],
                           "need_permission": _state.get("need_permission", False)}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    _dump_clients(force=True)
    threading.Thread(target=worker, daemon=True).start()
    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
                return
            super().handle_error(request, client_address)

    try:
        srv = QuietServer((HOST, PORT), Handler)
    except OSError as exc:
        if getattr(exc, "errno", None) == 48:
            print("port %d already in use, exit quietly" % PORT, flush=True)
            return
        raise
    srv.daemon_threads = True
    print(f"remote-view listening on http://{HOST}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
