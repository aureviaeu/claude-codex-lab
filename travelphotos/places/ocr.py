"""Read text (signs, station names, tickets) with the local OCR models."""

from __future__ import annotations

from .models import CHARSET, TEXT_DETECTOR, TEXT_RECOGNIZER, missing_models, model_dir

LIBS_MISSING = "缺少 OpenCV 或 numpy，無法辨識招牌文字。請重新用啟動檔啟動，讓它安裝需要的套件。"
MODELS_MISSING = (
    "還沒有下載文字辨識模型（約 75 MB，免費，只需要一次）。請連上網路後重新用啟動檔啟動，"
    "或在專案資料夾執行 .venv/bin/python launcher/download_models.py（Windows 用 .venv\\Scripts\\python）。"
)

DET_SIZE = 736  # PP-OCRv3 detection input (square)
REC_W, REC_H = 100, 32  # CRNN input
MAX_BOXES = 40  # text boxes read per image


class OcrUnavailable(Exception):
    """The OCR models or libraries are missing. The message is shown to the owner."""


class OpenCVOcr:
    """PP-OCRv3 text detection + CRNN recognition, run with OpenCV DNN on the CPU."""

    def __init__(self, directory: str):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:  # pragma: no cover - requirements include both
            raise OcrUnavailable(LIBS_MISSING) from exc
        if missing_models(directory):
            raise OcrUnavailable(MODELS_MISSING)
        import os

        self._cv, self._np = cv2, np
        det = cv2.dnn_TextDetectionModel_DB(os.path.join(directory, TEXT_DETECTOR.name))
        det.setBinaryThreshold(0.3)
        det.setPolygonThreshold(0.5)
        det.setUnclipRatio(2.0)
        det.setMaxCandidates(200)
        det.setInputParams(1.0 / 255.0, (DET_SIZE, DET_SIZE), (123.675, 116.28, 103.53), True)
        det.setInputScale(1.0 / 255.0 / np.array([0.229, 0.224, 0.225]))
        self._det = det
        self._rec = cv2.dnn.readNet(os.path.join(directory, TEXT_RECOGNIZER.name))
        with open(CHARSET, encoding="utf-8") as fh:
            self._charset = fh.read().splitlines()
        self._target = np.array([[0, REC_H - 1], [0, 0], [REC_W - 1, 0], [REC_W - 1, REC_H - 1]], dtype=np.float32)

    def read_text(self, rgb) -> list[str]:
        """Text lines found in an RGB image, top to bottom."""
        cv, np = self._cv, self._np
        bgr = cv.cvtColor(rgb, cv.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        boxes, _conf = self._det.detect(cv.resize(bgr, (DET_SIZE, DET_SIZE)))
        found: list[tuple[float, float, str]] = []
        for box in list(boxes)[:MAX_BOXES]:
            pts = np.array(box, dtype=np.float32)
            pts[:, 0] *= w / DET_SIZE
            pts[:, 1] *= h / DET_SIZE
            crop = cv.warpPerspective(bgr, cv.getPerspectiveTransform(pts, self._target), (REC_W, REC_H))
            self._rec.setInput(cv.dnn.blobFromImage(crop, size=(REC_W, REC_H), mean=127.5, scalefactor=1 / 127.5))
            text = self._decode(self._rec.forward())
            if text.strip():
                found.append((float(pts[:, 1].min()), float(pts[:, 0].min()), text))
        found.sort()
        return [t for _y, _x, t in found]

    def _decode(self, out) -> str:
        chars, prev = [], 0
        for i in range(out.shape[0]):
            k = int(self._np.argmax(out[i][0]))
            if k and k != prev and k - 1 < len(self._charset):
                chars.append(self._charset[k - 1])
            prev = k
        return "".join(chars)


def load_engine(base_dir: str | None = None) -> OpenCVOcr:
    return OpenCVOcr(model_dir(base_dir))
