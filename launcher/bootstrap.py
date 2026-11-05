"""Prepare a private environment and start the photo tool.

Called by start.command (macOS), start.bat (Windows) and start.sh (Linux).
Uses only the standard library so it runs before anything is installed.
See docs/decisions/0007-one-click-launcher.md.

- Creates `.venv/` inside the project folder (never touches the system Python).
- Installs requirements.txt into it, but only when the file changed since the
  last successful install (a hash is kept in `.venv/.travelphotos-requirements`).
- Starts `python -m travelphotos` with that environment.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv

MIN_PYTHON = (3, 10)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAMP_NAME = ".travelphotos-requirements"

TOO_OLD = (
    "這個工具需要 Python {need} 以上版本，目前是 {have}。\n"
    "請到 https://www.python.org/downloads/ 下載安裝最新版 Python，裝好後再執行一次啟動檔。"
)
NO_VENV = (
    "無法建立執行環境：這台電腦的 Python 缺少 venv／ensurepip 模組。\n"
    "Ubuntu／Debian 請先執行：sudo apt install python3-venv\n"
    "其他系統請到 https://www.python.org/downloads/ 安裝完整的 Python。"
)
PIP_FAILED = (
    "安裝需要的套件失敗。第一次啟動需要網路，從 Python 官方套件庫（PyPI）免費下載。\n"
    "請確認網路連線後再執行一次啟動檔。"
)


def venv_python(venv_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def requirements_digest(requirements: str) -> str:
    with open(requirements, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _read_stamp(venv_dir: str) -> str:
    try:
        with open(os.path.join(venv_dir, STAMP_NAME), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def needs_install(venv_dir: str, requirements: str) -> bool:
    return _read_stamp(venv_dir) != requirements_digest(requirements)


def _env_usable(python: str) -> bool:
    """The environment exists and has pip (a half-created one does not)."""
    if not os.path.isfile(python):
        return False
    try:
        done = subprocess.run(
            [python, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


class LaunchError(Exception):
    pass


def ensure_env(root: str = ROOT, log=print) -> str:
    """Create or update the project's environment. Returns its python path."""
    venv_dir = os.path.join(root, ".venv")
    requirements = os.path.join(root, "requirements.txt")
    python = venv_python(venv_dir)

    if not _env_usable(python):
        log("第一次啟動：正在建立執行環境（只在這個資料夾內，不會修改系統的 Python）…")
        try:
            venv.EnvBuilder(with_pip=True, clear=os.path.isdir(venv_dir)).create(venv_dir)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise LaunchError(f"{NO_VENV}\n（{exc}）") from None
        if not _env_usable(python):
            raise LaunchError(NO_VENV)

    if needs_install(venv_dir, requirements):
        log("正在安裝需要的套件（需要網路，只在第一次或套件更新時進行）…")
        cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements]
        if subprocess.call(cmd) != 0:
            raise LaunchError(PIP_FAILED)
        with open(os.path.join(venv_dir, STAMP_NAME), "w", encoding="utf-8") as fh:
            fh.write(requirements_digest(requirements) + "\n")
    else:
        log("套件已安裝，直接啟動。")
    return python


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    prepare_only = "--prepare-only" in args
    args = [a for a in args if a != "--prepare-only"]

    if sys.version_info < MIN_PYTHON:
        have = ".".join(map(str, sys.version_info[:3]))
        print(TOO_OLD.format(need=".".join(map(str, MIN_PYTHON)), have=have), file=sys.stderr)
        return 2
    try:
        python = ensure_env()
    except LaunchError as exc:
        print(exc, file=sys.stderr)
        return 1
    if prepare_only:
        return 0
    try:
        return subprocess.call([python, "-m", "travelphotos", *args], cwd=ROOT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
