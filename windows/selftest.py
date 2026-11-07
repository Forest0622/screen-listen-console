#!/usr/bin/env python3
"""源码级自检：不打包也能在 Windows 上跑一遍完整流程（CI 第一步）"""
import os
import sys
import tempfile

os.environ.setdefault("RV_DATA_DIR", tempfile.mkdtemp(prefix="sl-selftest-"))
os.environ.setdefault("RV_PORT", "16080")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app  # noqa: E402

sys.exit(app.run_selftest())
