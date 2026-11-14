# 0009 Local face recognition with OpenCV YuNet and SFace

## Context

Issue #6 keeps only photos and videos that show the owner and family. The owner decided (#3, #6): everything runs on this computer, nothing is uploaded, no paid or cloud service; people can be chosen both from reference photos and from automatic face groups; unsure faces are kept and marked "不確定"; group photos with strangers are kept; saved face data stays on this computer for the next trip and can be deleted with one button. CI has no face models and must stay offline-friendly.

## Decision

- **Models**: OpenCV Zoo YuNet (`face_detection_yunet_2023mar.onnx`, 0.2 MB, MIT) for detection and SFace (`face_recognition_sface_2021dec.onnx`, 38.7 MB, Apache-2.0) for 128-number face features, run with `opencv-python-headless` (`>=4.8,<5`) and `numpy`. Both added to `requirements.txt`.
- **Download once, then offline**: `launcher/download_models.py` fetches the two files from a URL pinned to one opencv_zoo commit and accepts them only when the SHA-256 matches. The launcher runs it on start; when the files are already there it only checks them. A failed download does not stop the tool; the page explains how to retry. The files live in the per-user data folder (`~/Library/Application Support/travelphotos/models`, `%LOCALAPPDATA%\travelphotos\models`, or `~/.local/share/travelphotos/models`; `TRAVELPHOTOS_DATA_DIR` overrides).
- **No network code in the app**: the download script is in `launcher/` next to the pip install, so the `travelphotos` package (including `travelphotos/faces/`) imports no network client. `tests/test_faces.py` checks every module's imports, and runs the whole face flow with sockets and DNS patched to fail.
- **Matching**: cosine similarity of SFace features. At or above 0.363 (OpenCV's recommended threshold) is the same person. From 0.28 to 0.363 for a selected person, and no saved person above 0.363, means "maybe": the file is kept and marked "不確定". A face that clearly matches a saved person who is not selected does not count as "maybe". Files that cannot be read (for example HEIC without `pillow-heif`) are kept and marked "不確定". Files with no face or only other faces are left out of the output and listed in the report with the reason.
- **Videos**: one frame every N seconds (default 2, range 0.2–600, at most 600 frames per video). A video is kept when any sampled frame has a selected person.
- **Groups**: greedy grouping of all faces from the scan (join when similarity to the group's average is at least 0.45), largest group first. Saving a group stores its feature vectors under a name.
- **Saved data**: `faces.json` in the same per-user folder, holding names and up to 60 feature vectors per person, written atomically with mode 0600. No photos or face images are saved. "刪除本機人臉資料" removes the file and clears the faces found in this session. Face crops for the page are cut on request from the scanned file and never stored.
- **Output**: `output.apply` takes an optional `FaceFilter`. Kept files are renumbered 1..n; left-out files are listed in `report.csv`/`report.json` with a new 人物篩選 column. An earlier output's files that are now left out are renamed `未使用_…`, as before; nothing is deleted.
- **Accuracy**: `python -m travelphotos.faces.evaluate --photos DIR --labels labels.csv --people 本人,媽媽` prints accuracy, precision and recall for a labelled set.
- **Tests**: a fake engine reads coloured squares in synthetic JPEG and MP4 files, so CI tests the real file reading, video sampling, matching, grouping, output and HTTP routes without the models. A test with the real models runs only where they are downloaded.

## Alternatives

- `face_recognition` / dlib: accurate, but dlib needs a C++ build on Windows and macOS.
- InsightFace / ONNX Runtime: more accurate models, but a larger download and the best models are licensed for non-commercial use only.
- MediaPipe: detection only, no recognition features.
- Cloud APIs: ruled out by the owner.
- Bundling the models in git: 39 MB of binary in the repository, and it would still need updating.

## Consequences

- First start needs about 39 MB more download (once). After that the face step works without a network.
- SFace is a small model. Side faces, small faces and children change more between photos, so expect more "不確定" files. Adding several reference photos per person, or adding groups from each trip to the same person, improves it. Revisit the thresholds or the model with the owner's real accuracy numbers.
- Detection runs inside the request, like scanning (0002). Many long videos make the page wait; revisit with a background job and progress bar if that is too slow.
- OpenCV 5 is not allowed yet; its graph engine prints warnings with these models. Revisit when it stabilises.
