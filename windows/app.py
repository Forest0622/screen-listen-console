#!/usr/bin/env python3
"""屏幕监听控制（Windows 版）入口

  ScreenListenConsole.exe                打开控制台
  ScreenListenConsole.exe --selftest     跑自检（CI 用）
      --selftest-out=<文件>              把自检结果写进文件（打包成窗口程序后没有 stdout）
"""
import json
import os
import sys
import tempfile


def _opt(prefix: str):
    for a in sys.argv[1:]:
        if a.startswith(prefix):
            return a[len(prefix):]
    return None


def _here() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _prepare_selftest_env() -> None:
    """自检用独立目录和独立端口，绝不动用户真实配置"""
    os.environ.setdefault("RV_DATA_DIR",
                          os.path.join(tempfile.gettempdir(), "screen-listen-selftest"))
    os.environ.setdefault("RV_PORT", "16080")


def run_selftest() -> int:
    _prepare_selftest_env()
    sys.path.insert(0, _here())
    import server as srv

    port = int(os.environ.get("RV_PORT", "16080"))
    ok, report = srv.run_selftest(port=port)
    report["frozen"] = bool(getattr(sys, "frozen", False))
    report["platform"] = sys.platform
    report["python"] = "%d.%d" % (sys.version_info[0], sys.version_info[1])
    try:
        import PIL
        report["pillow"] = PIL.__version__
    except Exception:
        report["pillow"] = "missing"

    text = json.dumps(report, ensure_ascii=False, indent=2)
    out = _opt("--selftest-out=") or os.path.join(tempfile.gettempdir(), "screen-listen-selftest.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return run_selftest()

    sys.path.insert(0, _here())
    import console
    console.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
