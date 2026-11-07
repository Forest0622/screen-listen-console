#!/usr/bin/env python3
"""局域网只读看屏服务（Windows 版）

与 macOS 版接口完全一致：
  GET /           查看页（带工具栏：暂停 / 缩放 / 全屏）
  GET /frame.jpg  最新一帧 JPEG
  GET /status     JSON 状态

实现差异只在于截图方式：Windows 用 Pillow 的 ImageGrab（GDI），不依赖外部命令。
账号密码同样从 config.json 读取，首次运行随机生成，改文件即时生效。
"""
import base64
import io
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = int(os.environ.get("RV_PORT", "6080"))
TARGET_WIDTH = 1600
JPEG_QUALITY = 55
INTERVAL = 1.0
IDLE_SLEEP = 2.0
STALE_SEC = 20.0


def _default_data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ScreenListenConsole")


DATA_DIR = os.environ.get("RV_DATA_DIR") or _default_data_dir()
LOG_DIR = os.path.join(DATA_DIR, "logs")
CLIENTS_FILE = os.path.join(LOG_DIR, "clients.json")
ACCESS_LOG = os.path.join(LOG_DIR, "access.log")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

DEFAULT_USER = "admin"
PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
_cred_lock = threading.Lock()
_cred = {"user": DEFAULT_USER, "password": "", "mtime": -1.0}


def _ensure_dirs() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def _random_password(n: int = 12) -> str:
    return "".join(secrets.choice(PW_ALPHABET) for _ in range(n))


def _write_config(user: str, password: str) -> None:
    _ensure_dirs()
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"user": user, "password": password}, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, CONFIG_FILE)


def current_credentials() -> dict:
    """读取 config.json；不存在则生成随机密码；文件改动后自动生效"""
    with _cred_lock:
        if not os.path.exists(CONFIG_FILE):
            pw = _random_password()
            _write_config(DEFAULT_USER, pw)
            print("[screen-listen] 首次运行，已生成访问密码：%s" % pw, flush=True)
        try:
            mtime = os.path.getmtime(CONFIG_FILE)
        except OSError:
            return dict(_cred)
        if mtime != _cred["mtime"]:
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    cfg = json.load(f)
                user = str(cfg.get("user") or DEFAULT_USER)
                pw = str(cfg.get("password") or "")
                if pw:
                    _cred.update(user=user, password=pw, mtime=mtime)
            except Exception:
                pass          # 文件正在写入时保持上一次的值
        return dict(_cred)


_clients_lock = threading.Lock()
_clients: dict = {}
_last_dump = 0.0


def _dump_clients(force: bool = False) -> None:
    global _last_dump
    with _clients_lock:
        now = time.time()
        if not force and now - _last_dump < 3.0:
            return
        _last_dump = now
        snapshot = [dict(v) for v in _clients.values()]
    try:
        _ensure_dirs()
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
        if path in ("/", "/index.html"):
            rec["pages"] += 1
    if path in ("/", "/index.html"):
        try:
            _ensure_dirs()
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            with open(ACCESS_LOG, "a", encoding="utf-8") as f:
                f.write("%s\t%s\t打开页面\n" % (stamp, ip))
        except Exception:
            pass
    _dump_clients(force=(path in ("/", "/index.html")))


_state = {"jpeg": None, "ts": 0.0, "error": None, "last_fetch": 0.0,
          "fails": 0, "blank": False}
_lock = threading.Lock()

HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>远程看屏</title>
<style>
 html,body{margin:0;height:100%;background:#111;color:#ddd;font:14px "Segoe UI",Helvetica,sans-serif}
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


def _grab_screen():
    """用 Pillow 抓屏；Windows 上 all_screens=True 会包含多显示器"""
    from PIL import ImageGrab
    try:
        return ImageGrab.grab(all_screens=True)
    except TypeError:
        return ImageGrab.grab()


def _to_jpeg(img) -> bytes:
    from PIL import Image
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > TARGET_WIDTH:
        height = max(1, int(round(img.height * TARGET_WIDTH / float(img.width))))
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        img = img.resize((TARGET_WIDTH, height), resample)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def capture_once() -> None:
    try:
        img = _grab_screen()
        data = _to_jpeg(img)
        blank = False
        try:
            extrema = img.convert("L").getextrema()
            blank = extrema[1] <= 2           # 全黑：常见于锁屏或非交互桌面会话
        except Exception:
            blank = False
        with _lock:
            _state["jpeg"] = data
            _state["ts"] = time.time()
            _state["error"] = ("抓到的是全黑画面（锁屏或非交互桌面会话），"
                               "解锁屏幕后会自动恢复") if blank else None
            _state["fails"] = 0
            _state["blank"] = blank
    except Exception as exc:
        with _lock:
            _state["fails"] = _state.get("fails", 0) + 1
            _state["error"] = "%s: %s" % (type(exc).__name__, exc)
            _state["blank"] = False


_server = None
_server_lock = threading.Lock()


def _worker() -> None:
    """抓屏循环：没人看的时候降频，失败后退避"""
    while _server is not None:
        idle = True
        with _lock:
            idle = (time.time() - _state["last_fetch"]) > 30
        try:
            capture_once()
        except Exception as exc:
            with _lock:
                _state["error"] = "%s: %s" % (type(exc).__name__, exc)
        with _lock:
            fails = _state.get("fails", 0)
            blank = _state.get("blank", False)
        if fails:
            delay = min(60.0, float(2 ** min(fails, 6)))
            if blank:
                delay = max(delay, 30.0)
        else:
            delay = IDLE_SLEEP if idle else INTERVAL
        deadline = time.time() + delay
        while _server is not None and time.time() < deadline:
            time.sleep(0.2)


class Handler(BaseHTTPRequestHandler):
    server_version = "ScreenListen/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
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
        cred = current_credentials()
        return user == cred["user"] and pw == cred["password"]

    def _require_auth(self) -> bool:
        if self._auth_ok():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="screen-listen"')
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
                jpeg, ts = _state["jpeg"], _state["ts"]
            if jpeg is None:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Time", "%.3f" % ts)
            self.end_headers()
            self.wfile.write(jpeg)
            return
        if path == "/status":
            with _lock:
                fresh = bool(_state["ts"]) and (time.time() - _state["ts"]) < STALE_SEC
                payload = {"ok": bool(_state["error"] is None and fresh),
                           "age_sec": round(time.time() - _state["ts"], 2) if _state["ts"] else None,
                           "error": _state["error"],
                           "need_permission": False}
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


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def start_server(port: int = None) -> None:
    """在当前进程内启动服务（GUI 也用这个入口）"""
    global _server
    with _server_lock:
        if _server is not None:
            return
        _ensure_dirs()
        current_credentials()
        _dump_clients(force=True)
        with _lock:
            _state["jpeg"] = None
            _state["ts"] = 0.0
            _state["error"] = None
            _state["fails"] = 0
            _state["blank"] = False
        srv = QuietServer((HOST, PORT if port is None else int(port)), Handler)
        _server = srv
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.3},
                         daemon=True).start()
        threading.Thread(target=_worker, daemon=True).start()


def stop_server() -> None:
    global _server
    with _server_lock:
        srv, _server = _server, None
    if srv is not None:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass


def is_running() -> bool:
    return _server is not None


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------- 自检

def _http(url: str, user: str, pw: str, timeout: float = 5.0):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url)
    token = base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        return 0, str(exc).encode()


def run_selftest(port: int = 16080, capture_timeout: float = 20.0):
    """真实跑一遍：配置生成 / 认证 / 出帧 / 热加载 / 页面内容"""
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})

    _ensure_dirs()
    cred = current_credentials()
    add("config 存在", os.path.exists(CONFIG_FILE), CONFIG_FILE)
    add("密码长度 12", len(cred["password"]) == 12, cred["password"])
    add("默认账号 admin", cred["user"] == "admin", cred["user"])

    try:
        start_server(port=port)
    except OSError as exc:
        add("端口可监听", False, exc)
        return False, {"checks": checks}

    base = "http://127.0.0.1:%d" % port
    add("服务已启动", is_running(), base)

    # 等第一帧（抓屏可能因锁屏/非交互会话拿不到）
    deadline = time.time() + capture_timeout
    status = {}
    while time.time() < deadline:
        code, body = _http(base + "/status", cred["user"], cred["password"])
        if code == 200:
            try:
                status = json.loads(body.decode("utf-8"))
            except Exception:
                status = {}
            if status.get("age_sec") is not None:
                break
        time.sleep(1.0)

    add("未登录访问返回 401", _http(base + "/status", "admin", "wrongpass")[0] == 401)
    add("错误账号返回 401", _http(base + "/status", "nobody", cred["password"])[0] == 401)
    add("正确密码返回 200", _http(base + "/status", cred["user"], cred["password"])[0] == 200)
    add("状态接口有 age_sec", status.get("age_sec") is not None, status)
    add("抓屏 ok（锁屏/无桌面会话时可能为 warn）",
        bool(status.get("ok")), status.get("error"))

    code, body = _http(base + "/frame.jpg", cred["user"], cred["password"])
    is_jpeg = body[:2] == b"\xff\xd8" if body else False
    add("出帧是 JPEG", code == 200 and is_jpeg, "code=%s size=%s" % (code, len(body or b"")))

    code, body = _http(base + "/", cred["user"], cred["password"])
    add("查看页可打开", code == 200 and "远程看屏".encode() in (body or b""), "code=%s" % code)
    add("未知路径返回 404", _http(base + "/nope", cred["user"], cred["password"])[0] == 404)

    # 热加载：改文件后立刻生效，不用重启
    old_pw = cred["password"]
    _write_config(cred["user"], "SelfTest2026")
    time.sleep(0.3)
    new_ok = _http(base + "/status", cred["user"], "SelfTest2026")[0] == 200
    old_bad = _http(base + "/status", cred["user"], old_pw)[0] == 401
    add("改配置即时生效", new_ok and old_bad, "new=%s old=%s" % (new_ok, old_bad))
    _write_config(cred["user"], old_pw)
    time.sleep(0.3)
    add("改回后恢复", _http(base + "/status", cred["user"], old_pw)[0] == 200)

    stop_server()
    add("服务可停止", not is_running())

    ok = all(c["ok"] for c in checks if "warn" not in c["check"])
    return ok, {"checks": checks, "capture_ok": bool(status.get("ok"))}


def main() -> None:
    _ensure_dirs()
    current_credentials()
    _dump_clients(force=True)
    try:
        start_server()
    except OSError as exc:
        print("端口占用或无法监听：%s" % exc, flush=True)
        return
    print("screen-listen 监听 http://%s:%d" % (HOST, PORT), flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        port = PORT
        for i, a in enumerate(sys.argv):
            if a == "--selftest-port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        ok, report = run_selftest(port=port)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)
    main()
