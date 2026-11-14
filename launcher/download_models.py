"""Download the local model files once: python launcher/download_models.py

This is the only network code for the face (#6) and place (#7) features. It lives in launcher/,
next to the pip install, so the travelphotos package stays free of network
code (tests check that): it fetches public model files (pinned URL and
SHA-256) and never sends photos or face data anywhere. After this, face
recognition and sign-text reading run offline. The launcher calls it on start
when the files are missing. See docs/decisions/0009-local-face-recognition.md and
docs/decisions/0010-local-place-matching.md.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from travelphotos.faces import paths  # noqa: E402
from travelphotos.places import models as place_models  # noqa: E402

TIMEOUT = 60


def all_models() -> tuple:
    """Face models first (small, needed by #6), then the OCR models (#7)."""
    return tuple(paths.MODELS) + tuple(place_models.MODELS)


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(model: paths.ModelFile, target: str, opener=urllib.request.urlopen) -> None:
    folder = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(prefix=".download-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as out, opener(model.url, timeout=TIMEOUT) as resp:
            for chunk in iter(lambda: resp.read(1024 * 1024), b""):
                out.write(chunk)
        got = sha256_of(tmp)
        if got != model.sha256:
            raise OSError(f"{model.name} 檢查碼不符（{got}），已丟棄。")
        os.replace(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def ensure_models(directory: str | None = None, log=print, opener=urllib.request.urlopen) -> bool:
    """Download missing or damaged model files. Returns True when all are present."""
    directory = directory or paths.model_dir()
    os.makedirs(directory, exist_ok=True)
    ok = True
    for model in all_models():
        target = os.path.join(directory, model.name)
        if os.path.isfile(target) and sha256_of(target) == model.sha256:
            continue
        log(f"正在下載模型 {model.name}（{model.size / 1_000_000:.1f} MB，只需要一次）…")
        try:
            _fetch(model, target, opener)
        except (OSError, ValueError) as exc:
            log(f"下載 {model.name} 失敗：{exc}")
            ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    if ensure_models():
        print(f"人臉與文字辨識模型已就緒：{paths.model_dir()}")
        return 0
    print("模型下載失敗。請確認網路連線後再執行一次；其他功能不受影響。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
