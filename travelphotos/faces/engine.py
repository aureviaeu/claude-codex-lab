"""Face detector and recognizer: OpenCV YuNet + SFace, run locally.

An engine turns one RGB image (numpy array, height x width x 3, uint8) into a
list of faces with an L2-normalised feature vector each. Tests use a fake
engine with the same `detect` method.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import paths

# Minimum detector confidence. Lower than OpenCV's demo (0.9) so blurry or
# side faces still reach the recognizer; matching marks those "uncertain".
DETECT_SCORE = 0.7
# Faces smaller than this (pixels, shorter side) are not recognised reliably.
MIN_FACE = 16


class FaceUnavailable(Exception):
    """Face features cannot run. The message is shown to the owner."""


@dataclass
class Face:
    box: tuple[int, int, int, int]  # x, y, w, h in the analysed image
    score: float
    embedding: list[float]  # L2-normalised


MODELS_MISSING = (
    "還沒有人臉模型檔。用啟動檔（start.command／start.bat／start.sh）重新啟動時會自動下載"
    "（只需要一次，約 39 MB，免費，需要網路；之後完全離線使用）。"
    "也可以在專案資料夾執行：python launcher/download_models.py"
)
LIBS_MISSING = "缺少 opencv-python-headless 或 numpy 套件。請重新執行啟動檔，或執行 pip install -r requirements.txt。"


class OpenCVEngine:
    def __init__(self, model_directory: str):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise FaceUnavailable(LIBS_MISSING) from exc
        if paths.missing_models(model_directory):
            raise FaceUnavailable(MODELS_MISSING)
        self._np = np
        self._detector = cv2.FaceDetectorYN.create(
            os.path.join(model_directory, paths.DETECTOR.name), "", (320, 320), DETECT_SCORE, 0.3, 5000
        )
        self._recognizer = cv2.FaceRecognizerSF.create(os.path.join(model_directory, paths.RECOGNIZER.name), "")

    def detect(self, rgb) -> list[Face]:
        np = self._np
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        h, w = bgr.shape[:2]
        self._detector.setInputSize((w, h))
        _ok, rows = self._detector.detect(bgr)
        faces: list[Face] = []
        if rows is None:
            return faces
        for row in rows:
            if min(row[2], row[3]) < MIN_FACE:
                continue
            aligned = self._recognizer.alignCrop(bgr, row)
            feat = self._recognizer.feature(aligned).reshape(-1).astype("float64")
            norm = float(np.linalg.norm(feat))
            if norm == 0.0:
                continue
            box = tuple(int(round(v)) for v in row[:4])
            faces.append(Face(box=box, score=float(row[14]), embedding=(feat / norm).tolist()))
        return faces


def load_engine(base_dir: str | None = None) -> OpenCVEngine:
    return OpenCVEngine(paths.model_dir(base_dir))
