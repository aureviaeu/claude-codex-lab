"""Read text (signs, station names, tickets, maps) with local OCR models (#22).

PP-OCRv3: DB text detection (OpenCV DNN), text direction classifier and
SVTR recognizer with 6623 characters, traditional included (onnxruntime).
Detection keeps the photo's aspect ratio and runs at two sizes; tall boxes
(vertical writing) are turned on their side, and upside-down lines are
turned upright. Everything runs on this computer.
"""

from __future__ import annotations

import os

from .models import (
    LEGACY_CHARSET,
    LEGACY_DETECTOR,
    LEGACY_RECOGNIZER,
    TEXT_DETECTOR,
    TEXT_DIRECTION,
    TEXT_RECOGNIZER,
    missing_models,
    model_dir,
)

LIBS_MISSING = "缺少 OpenCV、numpy 或 onnxruntime，無法辨識招牌文字。請重新用啟動檔啟動，讓它安裝需要的套件。"
MODELS_MISSING = (
    "還沒有下載文字辨識模型（約 12 MB，免費，只需要一次）。請連上網路後重新用啟動檔啟動，"
    "或在專案資料夾執行 .venv/bin/python launcher/download_models.py（Windows 用 .venv\\Scripts\\python）。"
)

MODELS_BROKEN = (
    "文字辨識模型檔無法載入，可能已損壞。請關閉這個工具，再用啟動檔（start.command／start.bat／start.sh）重新啟動："
    "啟動檔會檢查模型檔的校驗碼，損壞的會自動重新下載（需要網路）。"
)

SCALES = (736, 1280)  # longest side for detection; small and large text
REC_HEIGHT = 48
REC_MAX_WIDTH = 1600
CLS_SHAPE = (48, 192)
MAX_BOXES = 80  # text boxes read per image (all scales)
BIN_THRESH, BOX_THRESH, UNCLIP = 0.3, 0.5, 1.6
UPSIDE_DOWN = 0.9  # direction classifier confidence needed to turn a line


class OcrUnavailable(Exception):
    """The OCR models or libraries are missing. The message is shown to the owner."""


def _det_size(h: int, w: int, limit: int) -> tuple[int, int]:
    scale = min(1.0, limit / max(h, w))
    return max(32, int(round(h * scale / 32)) * 32), max(32, int(round(w * scale / 32)) * 32)


class OnnxOcr:
    def __init__(self, directory: str):
        try:
            import cv2
            import numpy as np
            import onnxruntime as ort
        except ImportError as exc:
            raise OcrUnavailable(LIBS_MISSING) from exc
        if missing_models(directory):
            raise OcrUnavailable(MODELS_MISSING)
        self._cv, self._np = cv2, np
        # A model that is present but cannot be parsed (damaged file) gives a
        # clear message (#26). onnxruntime's load errors subclass RuntimeError;
        # OSError and MemoryError are not caught and reach the server's
        # generic handler instead of being called "damaged".
        try:
            self._det = cv2.dnn.readNet(os.path.join(directory, TEXT_DETECTOR.name))
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            providers = ["CPUExecutionProvider"]
            self._rec = ort.InferenceSession(os.path.join(directory, TEXT_RECOGNIZER.name), opts, providers=providers)
            self._cls = ort.InferenceSession(os.path.join(directory, TEXT_DIRECTION.name), opts, providers=providers)
            keys = self._rec.get_modelmeta().custom_metadata_map.get("character", "")
        except (cv2.error, ValueError, RuntimeError) as exc:
            raise OcrUnavailable(MODELS_BROKEN) from exc
        if not keys:
            raise OcrUnavailable(MODELS_BROKEN)
        # CTC: index 0 is blank, then the model's characters, then a space.
        self._chars = [""] + keys.splitlines() + [" "]

    # --- detection -----------------------------------------------------
    def boxes(self, bgr, limit: int) -> list:
        cv, np = self._cv, self._np
        h, w = bgr.shape[:2]
        nh, nw = _det_size(h, w, limit)
        x = cv.resize(bgr, (nw, nh))[:, :, ::-1].astype(np.float32) / 255.0
        x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
        self._det.setInput(x.transpose(2, 0, 1)[None].astype(np.float32))
        prob = self._det.forward().reshape(nh, nw)
        mask = (prob > BIN_THRESH).astype(np.uint8)
        contours, _ = cv.findContours(mask, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
        out = []
        for c in contours:
            if cv.contourArea(c) < 9:
                continue
            x0, y0, bw, bh = cv.boundingRect(c)
            region = np.zeros((bh, bw), np.uint8)
            cv.drawContours(region, [c - (x0, y0)], -1, 1, -1)
            if prob[y0 : y0 + bh, x0 : x0 + bw][region.astype(bool)].mean() < BOX_THRESH:
                continue
            (cx, cy), (rw, rh), angle = cv.minAreaRect(c)
            perimeter = 2 * (rw + rh)
            if perimeter <= 0:
                continue
            grow = rw * rh * UNCLIP / perimeter
            rw, rh = rw + 2 * grow, rh + 2 * grow
            if min(rw, rh) < 5:
                continue
            pts = cv.boxPoints(((cx, cy), (rw, rh), angle)).astype(np.float32)
            pts[:, 0] = np.clip(pts[:, 0] * w / nw, 0, w - 1)
            pts[:, 1] = np.clip(pts[:, 1] * h / nh, 0, h - 1)
            out.append(pts)
        return out

    def _crop(self, bgr, pts):
        cv, np = self._cv, self._np
        s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
        p = np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)
        w = int(max(np.linalg.norm(p[0] - p[1]), np.linalg.norm(p[3] - p[2]), 4))
        h = int(max(np.linalg.norm(p[0] - p[3]), np.linalg.norm(p[1] - p[2]), 4))
        dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
        crop = cv.warpPerspective(bgr, cv.getPerspectiveTransform(p, dst), (w, h), borderMode=cv.BORDER_REPLICATE)
        if h > 1.5 * w:  # vertical writing: lay it on its side, as the recognizer was trained
            crop = cv.rotate(crop, cv.ROTATE_90_COUNTERCLOCKWISE)
        return crop

    # --- recognition ---------------------------------------------------
    def _blob(self, img, height: int, width: int):
        cv, np = self._cv, self._np
        w = min(width, max(8, int(np.ceil(height * img.shape[1] / img.shape[0]))))
        x = (cv.resize(img, (w, height)).astype(np.float32) / 255.0 - 0.5) / 0.5
        out = np.zeros((3, height, width), np.float32)
        out[:, :, :w] = x.transpose(2, 0, 1)
        return out

    def _upright(self, crop):
        np = self._np
        x = self._blob(crop, *CLS_SHAPE)[None]
        p = self._cls.run(None, {self._cls.get_inputs()[0].name: x})[0][0]
        if p[1] > p[0] and p[1] >= UPSIDE_DOWN:
            return np.ascontiguousarray(crop[::-1, ::-1])
        return crop

    def _read(self, crop) -> str:
        np = self._np
        width = min(REC_MAX_WIDTH, max(REC_HEIGHT, int(np.ceil(REC_HEIGHT * crop.shape[1] / crop.shape[0]))))
        x = self._blob(crop, REC_HEIGHT, width)[None]
        row = self._rec.run(None, {self._rec.get_inputs()[0].name: x})[0][0]
        chars, prev = [], 0
        for k in row.argmax(1):
            k = int(k)
            if k and k != prev and k < len(self._chars):
                chars.append(self._chars[k])
            prev = k
        return "".join(chars).strip()

    def read_text(self, rgb) -> list[str]:
        """Text lines found in an RGB image (both detection sizes, duplicates removed)."""
        cv = self._cv
        bgr = cv.cvtColor(rgb, cv.COLOR_RGB2BGR)
        found: list[tuple[float, float, str]] = []
        boxes = [b for limit in SCALES for b in self.boxes(bgr, limit)][:MAX_BOXES]
        for pts in boxes:
            text = self._read(self._upright(self._crop(bgr, pts)))
            if text:
                found.append((float(pts[:, 1].min()), float(pts[:, 0].min()), text))
        found.sort()
        return list(dict.fromkeys(t for _y, _x, t in found))


class LegacyZooOcr:
    """The engine before #22 (OpenCV Zoo PP-OCRv3 + CRNN, 3944 simplified characters).

    Kept only so the benchmark can show the before/after numbers on a
    computer that still has its model files.
    """

    def __init__(self, directory: str):
        import cv2
        import numpy as np

        det_path, rec_path = os.path.join(directory, LEGACY_DETECTOR), os.path.join(directory, LEGACY_RECOGNIZER)
        if not (os.path.isfile(det_path) and os.path.isfile(rec_path)):
            raise OcrUnavailable("沒有舊版的文字辨識模型，無法比較。")
        self._cv, self._np = cv2, np
        det = cv2.dnn_TextDetectionModel_DB(det_path)
        det.setBinaryThreshold(0.3)
        det.setPolygonThreshold(0.5)
        det.setUnclipRatio(2.0)
        det.setMaxCandidates(200)
        det.setInputParams(1.0 / 255.0, (736, 736), (123.675, 116.28, 103.53), True)
        det.setInputScale(1.0 / 255.0 / np.array([0.229, 0.224, 0.225]))
        self._det = det
        self._rec = cv2.dnn.readNet(rec_path)
        with open(LEGACY_CHARSET, encoding="utf-8") as fh:
            self._charset = fh.read().splitlines()
        self._target = np.array([[0, 31], [0, 0], [99, 0], [99, 31]], dtype=np.float32)

    def read_text(self, rgb) -> list[str]:
        cv, np = self._cv, self._np
        bgr = cv.cvtColor(rgb, cv.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        boxes, _ = self._det.detect(cv.resize(bgr, (736, 736)))
        out = []
        for box in list(boxes)[:40]:
            pts = np.array(box, dtype=np.float32)
            pts[:, 0] *= w / 736
            pts[:, 1] *= h / 736
            crop = cv.warpPerspective(bgr, cv.getPerspectiveTransform(pts, self._target), (100, 32))
            self._rec.setInput(cv.dnn.blobFromImage(crop, size=(100, 32), mean=127.5, scalefactor=1 / 127.5))
            o = self._rec.forward()
            chars, prev = [], 0
            for i in range(o.shape[0]):
                k = int(np.argmax(o[i][0]))
                if k and k != prev and k - 1 < len(self._charset):
                    chars.append(self._charset[k - 1])
                prev = k
            if chars:
                out.append("".join(chars))
        return out


def load_engine(base_dir: str | None = None) -> OnnxOcr:
    return OnnxOcr(model_dir(base_dir))
