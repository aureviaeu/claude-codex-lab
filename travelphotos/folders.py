"""Folder browsing for the in-page folder picker (docs/decisions/0006-in-page-folder-picker.md).

Only folder names and paths are returned, never file names or file contents.
The only write is `make_folder`, which creates one new, empty folder.
"""

from __future__ import annotations

import os
import stat
import string

# Characters that are not allowed in a folder name on at least one supported system.
_BAD_NAME_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
_MAX_NAME = 255


class FolderError(ValueError):
    """A problem the owner can fix; the message is shown in the page."""


def home() -> str:
    return os.path.abspath(os.path.expanduser("~"))


def roots() -> list[str]:
    """Drive letters on Windows (e.g. C:\\); the single root elsewhere."""
    if os.name == "nt":
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]
    return [os.path.abspath(os.sep)]


def _normalize(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return home()
    if "\x00" in path:
        raise FolderError("資料夾路徑不正確。")
    return os.path.abspath(os.path.expanduser(path))


def _is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    hidden = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0)
    return bool(attrs & hidden)


def list_folders(path: str) -> dict:
    """List the sub-folders of `path` (the home folder when empty)."""
    path = _normalize(path)
    if not os.path.exists(path):
        raise FolderError(f"找不到資料夾：{path}")
    if not os.path.isdir(path):
        raise FolderError(f"這不是資料夾：{path}")
    folders = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if not entry.is_dir() or _is_hidden(entry):
                        continue
                except OSError:
                    continue
                folders.append({"name": entry.name, "path": os.path.join(path, entry.name)})
    except PermissionError:
        raise FolderError(f"沒有權限讀取這個資料夾：{path}") from None
    except OSError as exc:
        raise FolderError(f"無法讀取這個資料夾：{path}（{exc.strerror or exc}）") from None
    folders.sort(key=lambda f: f["name"].casefold())
    parent = os.path.dirname(path)
    return {
        "path": path,
        "parent": parent if parent != path else None,
        "home": home(),
        "roots": roots(),
        "folders": folders,
    }


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise FolderError("請輸入新資料夾的名稱。")
    if name in {".", ".."} or any(ch in _BAD_NAME_CHARS for ch in name):
        raise FolderError('資料夾名稱不能是「.」或「..」，也不能包含 / \\ : * ? " < > | 這些符號。')
    if name.endswith("."):
        raise FolderError("資料夾名稱不能以「.」結尾。")
    if len(name) > _MAX_NAME:
        raise FolderError("資料夾名稱太長。")
    return name


def make_folder(parent: str, name: str) -> dict:
    """Create one new folder `name` inside `parent` and return its listing."""
    name = validate_name(name)
    parent = _normalize(parent)
    if not os.path.isdir(parent):
        raise FolderError(f"找不到資料夾：{parent}")
    target = os.path.join(parent, name)
    try:
        os.mkdir(target)
    except FileExistsError:
        raise FolderError(f"這裡已經有同名的資料夾或檔案：{name}") from None
    except PermissionError:
        raise FolderError(f"沒有權限在這裡建立資料夾：{parent}") from None
    except OSError as exc:
        raise FolderError(f"無法建立資料夾：{exc.strerror or exc}") from None
    return list_folders(target)
