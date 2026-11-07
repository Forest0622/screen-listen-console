#!/bin/bash
# 打包成可分发的 DMG 安装盘（内含 App + 指向「应用程序」的软链 + 使用说明）
# 用法：./make-dmg.sh [输出目录]
set -euo pipefail

APP_NAME="屏幕监听控制"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$ROOT/dist}"
APP="$OUT/$APP_NAME.app"

[ -d "$APP" ] || "$ROOT/make-app.sh" "$OUT"

STAGE="$OUT/dmg-stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
ditto "$APP" "$STAGE/$APP_NAME.app"
xattr -cr "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/应用程序"
cp "$ROOT/docs/使用说明.txt" "$STAGE/使用说明.txt"

DMG="$OUT/$APP_NAME-安装包.dmg"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME 安装包" -srcfolder "$STAGE" -format UDZO -ov "$DMG"
rm -rf "$STAGE"
echo "完成：$DMG"
