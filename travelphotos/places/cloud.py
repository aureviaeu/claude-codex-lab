"""Cloud place recognition: an option only, not implemented (#7).

The owner decided the first version uses local methods only. This module
fixes the shape of a future cloud step so it can be added in its own issue
after the owner chooses a service. Rules for that future step:

- it is off unless TRAVELPHOTOS_PLACES_CLOUD is set to 1/true/yes/on;
- it may only receive frames with no face, or with every face blurred;
- it is never called by this version: turning it on only adds a warning.
"""

from __future__ import annotations

import os
from typing import Protocol

ENV_FLAG = "TRAVELPHOTOS_PLACES_CLOUD"
NOT_IMPLEMENTED = (
    f"已設定 {ENV_FLAG} 開啟雲端景點辨識，但這個版本沒有實作雲端辨識，"
    "也不會上傳任何畫面；只使用本機方法。要啟用請另開 Issue 由負責人決定服務。"
)


class CloudPlaceRecognizer(Protocol):  # pragma: no cover - interface only
    def recognize(self, faceless_rgb, candidates: list[str]) -> list[tuple[str, float]]:
        """(candidate name, score) for one frame that has no visible face."""


def cloud_requested(environ=None) -> bool:
    value = (environ if environ is not None else os.environ).get(ENV_FLAG, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def cloud_recognizer(environ=None) -> CloudPlaceRecognizer | None:
    """Always None in this version: there is no cloud implementation."""
    return None


def cloud_warning(environ=None) -> str | None:
    return NOT_IMPLEMENTED if cloud_requested(environ) else None
