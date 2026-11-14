"""Where face data and model files live on this computer."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

ENV_DATA_DIR = "TRAVELPHOTOS_DATA_DIR"


@dataclass(frozen=True)
class ModelFile:
    name: str
    sha256: str
    url: str
    size: int


# OpenCV Zoo, pinned to one commit. YuNet is MIT licensed, SFace Apache-2.0.
_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/48b10fa505aeb51fbd127fc60a5c660040e823b7/models"
DETECTOR = ModelFile(
    "face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    232589,
)
RECOGNIZER = ModelFile(
    "face_recognition_sface_2021dec.onnx",
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    38696353,
)
MODELS = (DETECTOR, RECOGNIZER)


def data_dir() -> str:
    """Per-user folder for the face data and the models."""
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "travelphotos")


def model_dir(base: str | None = None) -> str:
    return os.path.join(base or data_dir(), "models")


def store_path(base: str | None = None) -> str:
    return os.path.join(base or data_dir(), "faces.json")


def missing_models(directory: str) -> list[str]:
    """Model files that are absent or have the wrong size (a cheap check)."""
    missing = []
    for m in MODELS:
        path = os.path.join(directory, m.name)
        if not os.path.isfile(path) or os.path.getsize(path) != m.size:
            missing.append(m.name)
    return missing
