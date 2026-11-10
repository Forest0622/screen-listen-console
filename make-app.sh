#!/bin/bash
# 编译并组装成一个可直接运行的 .app
# 用法：./make-app.sh [输出目录]      可选环境变量：SIGN_ID="证书名"（不填则为 ad-hoc 签名）
set -euo pipefail

APP_NAME="屏幕监听控制"
BIN_NAME="ScreenListenConsole"
BUNDLE_ID="com.xiaoyi.remoteview.console"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$ROOT/dist}"
APP="$OUT/$APP_NAME.app"

# 找 swiftc
SWIFTC="$(command -v swiftc || true)"
if [ -z "$SWIFTC" ]; then
  echo "未找到 swiftc，请先安装命令行工具：xcode-select --install" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "[1/4] 编译控制台…"
"$SWIFTC" -O "$ROOT/Console.swift" -o "$APP/Contents/MacOS/$BIN_NAME"

echo "[2/4] 拷贝资源…"
cp "$ROOT/server.py" "$APP/Contents/Resources/server.py"
[ -f "$ROOT/assets/AppIcon.icns" ] && cp "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

echo "[3/4] 写 Info.plist…"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>     <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>      <string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key>      <string>$BIN_NAME</string>
    <key>CFBundleIconFile</key>        <string>AppIcon</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleShortVersionString</key> <string>${VERSION:-1.3.4}</string>
    <key>CFBundleVersion</key>         <string>${BUILD_NUMBER:-8}</string>
    <key>CFBundleInfoDictionaryVersion</key> <string>6.0</string>
    <key>LSMinimumSystemVersion</key>  <string>11.0</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>NSPrincipalClass</key>        <string>NSApplication</string>
</dict>
</plist>
PLIST

echo "[4/4] 签名…"
xattr -cr "$APP"
if [ -n "${SIGN_ID:-}" ]; then
  codesign --force --deep -s "$SIGN_ID" "$APP"
  echo "已用证书签名：$SIGN_ID"
else
  codesign --force --deep -s - "$APP"
  echo "已 ad-hoc 签名（改代码后需要重新授权屏幕录制；固定身份请用 SIGN_ID 指定自签证书）"
fi

echo "完成：$APP"
