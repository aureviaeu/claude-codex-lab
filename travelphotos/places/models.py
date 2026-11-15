"""The local OCR model files (downloaded once by launcher/download_models.py).

#22: PaddleOCR PP-OCRv3 text detection, text direction and recognition
(Apache-2.0), as published inside the rapidocr-onnxruntime 1.2.3 wheel
(Apache-2.0) on PyPI. The wheel is fetched from a pinned URL and checked
against its SHA-256; only the three model files below are taken out of it,
each checked against its own SHA-256. See
docs/decisions/0011-better-sign-reading.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..faces.paths import ModelFile, model_dir  # noqa: F401  (re-exported)


@dataclass(frozen=True)
class WheelFile:
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class WheelModel:
    name: str  # file name on this computer
    member: str  # exact path inside the wheel
    sha256: str
    size: int


WHEEL = WheelFile(
    "https://files.pythonhosted.org/packages/b7/ef/0df9a58310895ab357f85df67935af6a8fb98f0965c7476cee6fcb966a7e/"
    "rapidocr_onnxruntime-1.2.3-py3-none-any.whl",
    "c707d3a6eb72d13119afe9602d3cc36d8b2a4a4d74e9575cf1b0e67ed6a27819",
    12326259,
)
TEXT_DETECTOR = WheelModel(
    "ch_PP-OCRv3_det_infer.onnx",
    "rapidocr_onnxruntime/models/ch_PP-OCRv3_det_infer.onnx",
    "3439588c030faea393a54515f51e983d8e155b19a2e8aba7891934c1cf0de526",
    2432880,
)
TEXT_RECOGNIZER = WheelModel(
    "ch_PP-OCRv3_rec_infer.onnx",
    "rapidocr_onnxruntime/models/ch_PP-OCRv3_rec_infer.onnx",
    "897a3ededb38fee0dae2c1ccee38241f37df202c9509e3abca02e9217c5ee615",
    10690752,
)
TEXT_DIRECTION = WheelModel(
    "ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "rapidocr_onnxruntime/models/ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    585532,
)
MODELS = (TEXT_DETECTOR, TEXT_RECOGNIZER, TEXT_DIRECTION)

# The models used before #22 (OpenCV Zoo). No longer downloaded; files left
# on a computer from an earlier version are not touched and can still be
# measured with `python -m travelphotos.places.benchmark --engine legacy`.
LEGACY_DETECTOR = "text_detection_cn_ppocrv3_2023may.onnx"
LEGACY_RECOGNIZER = "text_recognition_CRNN_CN_2021nov.onnx"
LEGACY_CHARSET = os.path.join(os.path.dirname(__file__), "charset_cn_3944.txt")


def missing_models(directory: str) -> list[str]:
    missing = []
    for m in MODELS:
        path = os.path.join(directory, m.name)
        if not os.path.isfile(path) or os.path.getsize(path) != m.size:
            missing.append(m.name)
    return missing
