# 0012 Run the browser and real-model tests in CI

## Context

Issue #31: the `test` check installed only what `scripts/test.sh` needs for the Python unit tests. Three Playwright browser tests (`tests/test_full_flow.py` `BrowserFlowTests`, `tests/test_errors.py` `PageMessageBrowserTests`) and the tests that load the real face and OCR models (`RealModelsOfflineTests`, `RealEngineTests`, `RealOcrTests`, `RealSignTests`) were skipped there, so `test` could be green while the page or the models were broken. `test` is the required check for branch protection and must keep its name. Models must be checked against the pinned SHA-256 and cached. No cloud or paid service, no owner photos.

## Decision

- **One job, still named `test`** (`.github/workflows/ci.yml`). It sets up Python 3.12 and Node 22, installs `requirements.txt`, installs Playwright, Chromium and its system libraries, installs `fonts-wqy-zenhei` (the CJK font `RealOcrTests` draws its sign with), downloads the models, and runs `scripts/test.sh`. One job keeps branch protection as it is: the required check is red unless every test in it passed.
- **Playwright pinned in `package.json` / `package-lock.json`** (exact version, npm integrity hashes) and installed with `npm ci`. It is a test-only tool; the app does not use Node, and `node_modules/` is ignored. The tests already find Playwright with `require.resolve('playwright')` from the repository, so no test code changed for this. The Chromium download is cached by the lockfile's hash.
- **Models through `launcher/download_models.py`**, the same code the launcher uses, so the pinned URLs and SHA-256 values in `travelphotos/faces/paths.py` and `travelphotos/places/models.py` stay the single source. `~/.local/share/travelphotos/models` is cached with a key made from those two files, so a changed pin downloads again. A cache hit is not trusted: the script hashes every file present and re-downloads (and re-checks) any that does not match, and the step fails when a download or check fails.
- **Missing environment fails instead of skipping in CI** (`tests/optional.py`). The optional-environment skips now go through `needs(...)` / `skip_or_fail(...)`. Without `TRAVELPHOTOS_REQUIRE_ALL_TESTS=1` they skip as before, so `scripts/test.sh` still passes on a computer without Node or models. CI sets it to `1`: then a missing browser, model or font fails the class with the reason, instead of a green run with tests left out. `tests/test_optional.py` checks both behaviours.
- `scripts/test.sh` is unchanged and is still the entry point CI calls; it picks the runner's Python because Pillow is installed there.

## Alternatives

- Separate `browser` and `models` jobs with a `test` job that `needs` them: parallel, but the required check then depends on `needs` and `if: always()` handling being right, and on the job graph not changing. One job is simpler; the run takes a few minutes either way.
- Docker image `mcr.microsoft.com/playwright`: bundles the browser and libraries, but pins a whole OS image and Python would still need setting up.
- Install Playwright for Python (`pip install playwright`) and rewrite the browser tests in Python: rewrites working tests; the Node scripts stay as they are.
- Fail CI when the unittest summary reports any skip (grep the log): catches future skips too, but also legitimate platform skips (Windows-only tests), and gives no reason. The explicit switch names what is missing.
- Commit the models or use Git LFS: 52 MB in the repository, and the launcher would still download them for users.

## Consequences

- The `test` run now downloads about 52 MB of models (first run or after a pin change), Chromium (first run or after a Playwright upgrade) and the apt packages Chromium needs (every run). Expect a few minutes per run.
- A UI regression that breaks a click-through now fails CI. Upgrading Playwright means bumping `package.json` and `package-lock.json` together.
- Any new test that needs an optional environment should use `tests/optional.needs`, and CI must install that environment.
- ADR 0011's note that CI has no models no longer holds.
