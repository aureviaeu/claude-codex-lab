"""The local OCR model files (downloaded once by launcher/download_models.py)."""

from __future__ import annotations

import os

from ..faces.paths import ModelFile, model_dir  # noqa: F401  (re-exported)

# OpenCV Zoo, pinned to the same commit as the face models. Both Apache-2.0.
_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/48b10fa505aeb51fbd127fc60a5c660040e823b7/models"
TEXT_DETECTOR = ModelFile(
    "text_detection_cn_ppocrv3_2023may.onnx",
    "03f550c6b406fda8bf54bd8327815f6c7e2edd98cea02348c93d879254366587",
    f"{_ZOO}/text_detection_ppocr/text_detection_cn_ppocrv3_2023may.onnx",
    2423490,
)
TEXT_RECOGNIZER = ModelFile(
    "text_recognition_CRNN_CN_2021nov.onnx",
    "c760bf82d684b87dfabb288e6c0f92d41a8cd6c1780661ca2c3cd10c2065a9ba",
    f"{_ZOO}/text_recognition_crnn/text_recognition_CRNN_CN_2021nov.onnx",
    72807160,
)
MODELS = (TEXT_DETECTOR, TEXT_RECOGNIZER)

# The recognizer's 3944 output characters, one per line, copied from
# opencv_zoo models/text_recognition_crnn/crnn.py (CHARSET_CN_3944).
CHARSET = os.path.join(os.path.dirname(__file__), "charset_cn_3944.txt")


def missing_models(directory: str) -> list[str]:
    missing = []
    for m in MODELS:
        path = os.path.join(directory, m.name)
        if not os.path.isfile(path) or os.path.getsize(path) != m.size:
            missing.append(m.name)
    return missing
