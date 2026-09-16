#!/bin/bash
# 启动「考研英语生词本」本机应用（macOS / Linux）。
# 首次使用前请先运行一次：python3 vocabulary_app/build_dict.py <ecdict.csv>
# 通常无需手动执行本脚本：直接双击“启动生词本.command”。
set -e
cd "$(dirname "$0")"

pick_python() {
  for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(pick_python)" || {
  echo "找不到 Python 3.10 或更高版本。"
  echo "请先安装：https://www.python.org/downloads/ 或 brew install python@3.12"
  read -r -p "按回车键关闭…" _
  exit 1
}

echo "使用解释器：$PYTHON"

# 离线词典查询库由仓库里的 data/dictionary 分片生成，不进版本库
if [ ! -f data/dict/dict.sqlite ]; then
  echo "首次运行：正在从 data/dictionary 生成离线词典（约 2 秒）…"
  "$PYTHON" -B vocabulary_app/build_dict.py --quiet || {
    echo "词典生成失败；不影响识别，但查词释义会缺失。"
    echo "可稍后手动运行：$PYTHON -B vocabulary_app/build_dict.py"
  }
fi

exec "$PYTHON" -B vocabulary_app/server.py "$@"
