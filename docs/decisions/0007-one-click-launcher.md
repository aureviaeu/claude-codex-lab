# 0007 One-click launcher with a private environment

## Context

The owner had to run `pip install -r requirements.txt` before `python3 -m travelphotos` (#10). The owner chose support for macOS, Windows and Linux, and starting by double-clicking a file instead of opening a terminal.

## Decision

- Three start files in the project root, one per system, each a thin wrapper:
  - `start.command` for macOS (Finder runs `.command` files in Terminal on double-click). It calls `start.sh`.
  - `start.bat` for Windows. It switches the console to UTF-8 for the Chinese messages. `.gitattributes` keeps it in CRLF line endings.
  - `start.sh` for Linux (and the shared logic for macOS). POSIX `sh`, so it also works with the old bash on macOS. When it is double-clicked without a terminal, it reopens itself in the first terminal emulator it finds so the messages stay visible.
- Each wrapper looks for Python 3.10 or newer (`python3`, `python`, versioned names; `py -3` first on Windows). If none is found, it prints in Chinese what to install and where, waits for Enter when there is a window, and exits. It never installs Python.
- The wrapper then runs `launcher/bootstrap.py`, which uses only the standard library:
  - Creates `.venv/` inside the project folder with `venv` (already in `.gitignore`), so the system Python and global packages are never changed. A half-created or broken `.venv/` (no working pip) is rebuilt.
  - Installs `requirements.txt` into `.venv/` only when the file's SHA-256 differs from the one saved after the last successful install (`.venv/.travelphotos-requirements`). A second start therefore does not contact PyPI at all; a changed `requirements.txt` installs automatically.
  - Explains in Chinese when `venv`/`ensurepip` is missing (Debian/Ubuntu need `python3-venv`) or when pip fails (first start needs internet).
  - Starts `python -m travelphotos` with the `.venv/` Python, passing any extra arguments through.
- `python -m travelphotos` now falls back to a free port when 8765 is taken (for example a second double-click), instead of failing with a traceback.
- `python3 -m travelphotos` keeps working for anyone who installs the packages themselves. `scripts/test.sh` uses the same `.venv/`.

## Alternatives

- A bundled app (`.app`, `.exe`, PyInstaller) or bundled Python: out of scope for #10, and needs code signing to avoid security warnings.
- `pipx` or `uv`: one more tool for the owner to install first.
- Putting all logic in each shell/batch file: three copies of the install logic in three languages, and the Windows one cannot be tested on Linux CI.
- A Linux `.desktop` file: needs an absolute path to the project, and current GNOME Files no longer runs `.desktop` files from ordinary folders.

## Consequences

- macOS may block the first double-click of a downloaded `start.command`; the README says to right-click → Open once. Linux file managers may need "Run as a Program" or executable text files enabled.
- `start.bat` is checked only by static tests here; the owner's acceptance on Windows is its real test.
