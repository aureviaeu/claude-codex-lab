# 0002 Python standard library web app with Pillow

## Context

Issue #5 is the first product code: a travel photo organiser that runs on the owner's computer, with a local web interface (decided on #3 and #5), no cloud, and drag-and-drop reordering. CI runs `scripts/test.sh` on `ubuntu-latest` and that check must keep its name. Later sub-issues (#6 faces, #7 places) will add image processing to the same app.

## Decision

- Python 3.10+ for the whole app, in the `travelphotos/` package. Start it with `python -m travelphotos`.
- The web server is the standard library `http.server` (`ThreadingHTTPServer`). The page is plain HTML, CSS, and JavaScript in `travelphotos/static/`, with no build step and nothing loaded from the internet.
- Pillow is the only runtime dependency (`requirements.txt`). It computes the similarity hash and the previews. If `pillow-heif` is installed, Pillow can also open HEIC; without it, HEIC files are still sorted by their EXIF time but get no preview and no similarity hash.
- EXIF and MP4/MOV times are read by a small parser in `travelphotos/metadata.py`, so reading times does not depend on Pillow or on HEIC support.
- Tests use the standard library `unittest`. `scripts/test.sh` keeps the repository checks from 0001 and then runs `python -m unittest discover -s tests`. When Pillow cannot be imported, it creates `.venv/` and installs `requirements.txt` there. This replaces the placeholder from 0001; the script path and the job name `test` are unchanged.

## Alternatives

- Node.js or Electron: a desktop window is nicer, but Electron is heavy and the image libraries we will need for faces and OCR in #6 and #7 are stronger in Python.
- Flask or FastAPI: nicer routing, but more dependencies for four endpoints.
- A frontend framework (React, Vue): needs a build step; the page is small.
- `pytest`: nicer output, but `unittest` needs nothing extra.

## Consequences

- The owner needs Python 3.10+ and `pip install -r requirements.txt` once. After that everything works offline.
- Scanning runs inside the request and the page waits. That is fine for a few thousand files; revisit with a background job and progress bar if scans get slow.
- Revisit the server choice if #6 or #7 needs streaming progress or many more endpoints.
