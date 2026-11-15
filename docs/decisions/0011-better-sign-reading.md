# 0011 Better sign reading: PP-OCRv3 on onnxruntime, Japanese forms and core names

## Context

Issue #22: on the owner's acceptance check of #21, 5 real sign photos gave 0 place names. The engine from #7 (ADR 0010) is OpenCV Zoo PP-OCRv3 detection squeezed to 736×736 plus a CRNN recognizer with 3944 simplified characters: it cannot read 嵐 or 稲, and Japanese signs often show only part of the itinerary name (伏見稲荷 for 伏見稻荷大社, 京都 for 京都車站). Constraints: local only, free, pinned models with checksums, offline after the first download, no regressions.

## Decision

Measured on 22 real photos from Wikimedia Commons (13 with a place name, 9 that must match nothing; `tests/data/signs`, `python -m travelphotos.places.benchmark`):

| Approach | Hits /13 | Wrong | False /9 | s/photo | Download |
| --- | --- | --- | --- | --- | --- |
| Before: zoo det 736² + CRNN 3944, old matching | 0 | 0 | 0 | 0.30 | 75 MB |
| Before engine + new matching | 2 | 0 | 0 | 0.30 | 75 MB |
| Zoo models, aspect-kept multi-scale, vertical handling + new matching | 2 | 0 | 0 | 0.8 | 75 MB |
| PP-OCRv3 det/cls/rec (onnxruntime), one scale + new matching | 7 | 0 | 0 | 0.24 | 12.3 MB |
| PP-OCRv3, scales 736 + 1280, old matching | 3 | 0 | 0 | 0.4 | 12.3 MB |
| **PP-OCRv3, scales 736 + 1280 + new matching (chosen)** | **8** | **0** | **0** | 0.4–0.5 | 12.3 MB |
| Chosen + itinerary aliases (嵐山（Arashiyama）) | 10 | 0 | 0 | 0.4 | 12.3 MB |
| rapidocr-onnxruntime package as shipped (reference) | 8 | 0 | 0 | 0.26 | — |

- **Engine** (`travelphotos/places/ocr.py`): PaddleOCR PP-OCRv3 DB detection run with OpenCV DNN, our own DB post-processing (OpenCV's built-in one only accepts the zoo model's output shape), detection at two sizes keeping the aspect ratio, tall boxes turned on their side, the PP-OCR direction classifier turning upside-down lines, and the PP-OCRv3 SVTR recognizer (6623 characters, traditional included) run with onnxruntime. OpenCV < 5 cannot load that recognizer; OpenCV 5 can, but the project stays below 5 (ADR 0009).
- **Models**: taken from the rapidocr-onnxruntime 1.2.3 wheel on PyPI (Apache-2.0; PaddleOCR models Apache-2.0). `launcher/download_models.py` downloads the wheel from a pinned URL, checks its SHA-256, copies out exactly three named members and checks each one's SHA-256, writing atomically; a failed check leaves no file. The old 75 MB zoo files are no longer downloaded and are left alone if present (`--engine legacy` in the benchmark uses them for the before numbers). Face models are unchanged.
- **New dependency**: `onnxruntime>=1.17,<2` (MIT, free wheels for Windows, macOS and Linux). Not used as a package: rapidocr-onnxruntime itself requires `opencv-python`, which clashes with `opencv-python-headless`.
- **Matching** (`travelphotos/places/matching.py`): Japanese kanji forms (稲, 駅, 広, …) are mapped to traditional before OpenCC's traditional→simplified. A stop's *core name* (its name without 車站/站/驛/大社/神社/神宮/公園) matches at medium confidence when a sign line is exactly the core (or core + station ending) for a station stop, or starts with a core of at least three characters for any other stop. So 京都 → 京都車站 and 伏見稲荷 → 伏見稻荷大社 match, while 京都市役所前, 京都河原町, 奈良 / 奈良駅 → 奈良公園 do not.
- **Itinerary aliases** (`travelphotos/itinerary.py`): a line may end with Latin-letter aliases in brackets, `嵐山（Arashiyama）` or `雷門 (Kaminarimon)`; they are used only for matching (whole words, as in ADR 0010). Brackets with anything else (`京都飯店（午餐）`) stay part of the name, as before.
- **Benchmark**: `python -m travelphotos.places.benchmark [--photos DIR --labels labels.csv --itinerary trip.txt] [--engine legacy] [--rules basic]` prints each photo's text, the stop and hit/miss/wrong/false-positive counts, using the app's own decision rule. The test set records source, author, license and changes per photo (`tests/data/signs/README.md`).

## Alternatives

- Tesseract: needs a separate system install on Windows and macOS. EasyOCR / full PaddleOCR: PyTorch or PaddlePaddle, hundreds of MB.
- PaddleOCR's Japanese recognizer (would read 嵐 and kana): not published on a source this project already pins (PyPI, GitHub); Hugging Face and ModelScope are not reachable from the build environment, so it could not be measured. 4 of the 5 remaining misses are 嵐 (嵐山); aliases recover 2 of them. Revisit with the owner's photos.
- Looser fuzzy matching to catch misread characters: brings back 嵐山↔富士山-type errors.
- Upgrading to OpenCV 5 instead of adding onnxruntime: face models print warnings there (ADR 0009).

## Consequences

- First start downloads 12.3 MB instead of 75 MB for text. Reading takes about 0.4–0.5 s per photo instead of 0.3 s.
- The 13 tuning photos were used to design the matching rules, so the 8/13 overstates new photos somewhat; 3 photos added after the rules were fixed (held-out: 奈良 station signs, fortune boxes) show no false match. No real ticket or map photo could be fetched (Commons rate limits); the owner can measure their own photos with the benchmark command.
- CI has no models: the matching rules, alias parsing, wheel extraction and benchmark counting are tested without models; the hit-rate, rotation and vertical-text tests run where the models are downloaded.
