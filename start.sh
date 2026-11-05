#!/bin/sh
# Start the travel photo tool (Linux; macOS uses start.command, Windows start.bat).
# Double-click it in the file manager ("Run" / "Run as a Program"), or run ./start.sh.
# The first run prepares a private environment in .venv/; later runs start directly.
# See docs/decisions/0007-one-click-launcher.md.

# Find this folder with shell built-ins only.
case "$0" in
  */*) here="${0%/*}" ;;
  *) here="." ;;
esac
cd "$here" || exit 1

# Double-clicked without a terminal: reopen in one so messages stay visible.
if [ ! -t 1 ] && [ -z "${TRAVELPHOTOS_IN_TERMINAL:-}" ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  TRAVELPHOTOS_IN_TERMINAL=1
  export TRAVELPHOTOS_IN_TERMINAL
  for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal mate-terminal lxterminal kitty alacritty xterm; do
    if command -v "$term" >/dev/null 2>&1; then
      case "$term" in
        gnome-terminal) exec "$term" -- /bin/sh ./start.sh "$@" ;;
        *) exec "$term" -e /bin/sh ./start.sh "$@" ;;
      esac
    fi
  done
fi

pause() {
  if [ -t 0 ] && [ -t 1 ]; then
    printf '按 Enter 關閉這個視窗。'
    read -r _
  fi
}

python=""
for candidate in python3 python python3.14 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    python="$candidate"
    break
  fi
done

if [ -z "$python" ]; then
  echo "找不到 Python 3.10 以上版本，無法啟動旅行照片整理。"
  echo "請安裝 Python 3.10 以上版本後，再執行一次這個啟動檔："
  echo "  - macOS／Windows：到 https://www.python.org/downloads/ 下載安裝。"
  echo "  - Linux：用套件管理員安裝，例如 Ubuntu／Debian：sudo apt install python3 python3-venv"
  pause
  exit 1
fi

"$python" launcher/bootstrap.py "$@"
status=$?
if [ "$status" -ne 0 ]; then
  pause
fi
exit "$status"
