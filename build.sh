#!/usr/bin/env bash
# ============================================================
#  Build GitBundleBackuper for Linux / macOS with PyInstaller
#  Usage:  bash build.sh
#  Output: dist/GitBundleBackuper
# ============================================================
set -e
cd "$(dirname "$0")"

# ---- locate python3 ----
PY=""
if command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "[ERROR] Python not found. Install Python 3 first." >&2
    exit 1
fi

echo "[1/3] Installing build dependencies ..."
"$PY" -m pip install -r requirements.txt pyinstaller

echo "[2/3] Building binary ..."
# 程序图标(Windows)已在 GitBundleBackuper.spec 中配置: icon=GitBundleBackuper.ico
# Linux/macOS 可执行文件不支持 Windows PE 图标资源，故此处仍调用同一 spec
# (macOS 如需 .app 图标请另行生成 .icns 并传入 spec)
"$PY" -m PyInstaller --noconfirm --clean GitBundleBackuper.spec

echo "[3/3] Done."
echo
echo "Output: $(pwd)/dist/GitBundleBackuper"
echo "Note: put the binary next to a \".git\" folder to auto-select it on start."
