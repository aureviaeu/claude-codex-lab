# 0010 Local place matching: OCR against the itinerary, then look-alike groups

## Context

Issue #7 asks which itinerary stop each group of photos and videos was taken at, without GPS or capture time, and a summary of the stops visited in order. The owner decided (#7 comment): the itinerary is written one place per line; the first version uses no cloud or paid service; the summary is a Markdown report; a stop visited twice (a hotel) is listed twice. Everything must run on this computer and work offline once the models are downloaded. CI has no models.

## Decision

- **Groups**: the groups from `ordering.build_groups` (0003). Each group is judged once and gets a stop with a confidence, or "未知".
- **OCR**: OpenCV Zoo PP-OCRv3 text detection (`text_detection_cn_ppocrv3_2023may.onnx`, 2.4 MB) and CRNN recognition (`text_recognition_CRNN_CN_2021nov.onnx`, 72.8 MB, 3944 characters, Chinese plus Latin letters and digits), both Apache-2.0, run with the existing `opencv-python-headless`. They are pinned to the same opencv_zoo commit as the face models and downloaded by `launcher/download_models.py` with a SHA-256 check. The recognizer's character list is copied from the zoo's `crnn.py` into `travelphotos/places/charset_cn_3944.txt`. Up to 8 files are read per group, and 3 frames (every 3 seconds) per video.
- **Matching text to stops**: text and stop names are normalised (NFKC, lower case, punctuation removed) and converted to simplified characters with `opencc-python-reimplemented` (pure Python, Apache-2.0, new dependency), because the OCR model writes simplified characters and the owner's itinerary uses traditional ones. A name found exactly scores 1.0 (high confidence). Names of three or more characters may also match a window of the same length that differs in one character only (one misread character); the score is the shared fraction, so 0.85 or more is high and 0.6 or more is medium. One- and two-character names (嵐山, 京都) must appear exactly, because one shared character is not evidence. Latin names are compared word by word, so "Nara" never matches inside "Narita". Two different places within 0.05 of each other leave the group "未知".
- **Local image comparison**: a group with no usable sign takes the place of the identified group it looks most like, comparing a 4×4-grid colour histogram (Pillow), only when the likeness is at least 0.8 and 0.05 ahead of any other place. Confidence is low.
- **Repeated stops**: groups are walked in time order, and a name that appears more than once in the itinerary takes the next occurrence.
- **Ordering**: automatic stops are written into the same `assignments` the page uses (0003), only for groups the owner has not set by hand, including groups the owner set back to 未對應 (kept until a new scan or until the owner picks a stop). A re-run replaces earlier automatic stops the owner left alone.
- **Output**: `places.md` (Markdown summary: stops in order, photo and video counts, confidence, a representative photo linked by its output name, stops with no photos, unknown files, and all text read), a 景點判斷 column in `report.csv`/`report.json`, and the summary in the page.
- **Cloud**: `travelphotos/places/cloud.py` only defines the shape of a future step (faceless frames only) and the `TRAVELPHOTOS_PLACES_CLOUD` switch. Turning it on adds a warning; nothing is called or uploaded. The package still imports no network client (tested).
- **Tests**: a fake OCR engine reads a coloured marker in synthetic JPEG and MP4 files, so CI tests grouping, matching, video frames, look-alikes, repeated stops, the summary, the output files and the HTTP route without the models. A test with the real models reads a rendered Chinese sign; it runs where the models are downloaded.

## Alternatives

- **A local image–text model (CLIP)**, as the spec listed: English CLIP cannot read the Chinese place names in the itinerary, Chinese-CLIP is about 300–600 MB, its files are not published on a pinned GitHub source this project already uses, and it would need `onnxruntime` and a tokenizer. The colour-layout comparison only extends places already found by OCR, so it cannot invent a wrong stop from a name alone. Revisit with the owner's real photos if too many groups stay "未知".
- **Tesseract**: needs a separate system install on Windows and macOS.
- **EasyOCR / PaddleOCR**: need PyTorch or PaddlePaddle, hundreds of MB.
- **A built-in traditional/simplified table**: smaller, but would miss many characters; OpenCC is the standard table.
- **Cloud landmark APIs**: ruled out by the owner for this version.

## Consequences

- First start downloads about 75 MB more (once). After that places work offline.
- Photos without signs depend on looking like a photo that has one; expect "未知" for many scenery shots. The owner can still pick a stop per group in the page; that wins over the automatic one.
- OCR runs inside the request like scanning (0002); a trip with many groups makes the page wait. Revisit with a background job if it is too slow.
- Japanese kana and Korean are not in the recognizer's character list; kanji place names are.
