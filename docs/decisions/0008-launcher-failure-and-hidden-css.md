# 0008 Launcher failures without a half-built environment, and a global `[hidden]` rule

## Context

Acceptance of PR #11 found two defects (#12):

1. On Debian/Ubuntu without `python3-venv`, `venv` prints an English note and calls `sys.exit(1)`. `launcher/bootstrap.py` caught only `OSError` and `CalledProcessError`, so the `SystemExit` escaped: the Chinese help never appeared and a half-built `.venv/` stayed behind.
2. The photo-folder picker showed 「在這裡建立資料夾」. `app.js` set `hidden` on the create row, but `.picker-new { display: flex }` in `style.css` overrides the browser's default `[hidden] { display: none }`.

## Decision

- `bootstrap.py` checks `importlib.util.find_spec("ensurepip")` before creating anything, and wraps environment creation in `except (Exception, SystemExit)`. Any failure ends in the Chinese `NO_VENV` message and exit code 1. The message says to run the start file again after installing, with no manual clean-up.
- After a failed creation, `.venv/` is removed. The launcher only ever creates, rebuilds, or removes a `.venv/` that is missing or that `venv` made (it contains `pyvenv.cfg`). A rebuild empties the old environment first, so a failed attempt's directory holds only what that attempt wrote. A `.venv` that is not a Python environment, or is a symlink, is never touched; the launcher asks the owner to rename or move it.
- `style.css` has `[hidden] { display: none !important; }`, so the `hidden` attribute always wins over author `display` rules for every element on the page, not just the picker.
- Regression tests: `tests/test_launcher.py` drives `ensure_env` with a fake builder that behaves like Debian's (writes `pyvenv.cfg`, then `SystemExit`), retries, then recovers with a working builder. `tests/test_static_ui.py` checks the `[hidden]` rule and that only the output picker enables the create row. CI has no browser, so the visual check was done once by hand with Chromium.

## Alternatives

- Run `python -m venv` in a subprocess and read its exit code: also catches `SystemExit`, but the existing in-process `EnvBuilder` already works on macOS and Windows, and the subprocess route still needs the same clean-up.
- Leave a failed `.venv/` and rebuild it next time (it already had `clear=True`): the owner saw this as a confusing state, and a later run could still fail the same way before reaching the rebuild.
- Fix only `.picker-new` (for example `.picker-new[hidden] { display: none; }`): the same bug would come back the next time a hidden element gets a `display` rule.
- A browser test in CI (Playwright): adds a large dependency to CI for one CSS rule.

## Consequences

- If a future element must be shown while it has the `hidden` attribute, the attribute has to be removed instead; that is the intended meaning of `hidden`.
- Debian's English note may still print just before the Chinese help, because `venv` writes it itself. The Chinese help is always the last thing shown.
