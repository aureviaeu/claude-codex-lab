# 0006 Picking folders with an in-page folder browser

## Context

The owner had to type full folder paths for the photo folder and the output folder (#10). The tool needs the real path on this computer, because the server reads the photos and copies them in place. A browser's own file picker (`<input type="file" webkitdirectory>`) does not give the page the folder's full path, so it cannot be used for this.

## Decision

- The page has a "選擇…" button next to each path field. It opens a dialog that lists sub-folders and lets the owner go into a folder, go up one level, jump to the home folder, switch drives on Windows, and choose the current folder. The text fields stay, so a path can still be pasted.
- When the output field is empty, its picker starts next to the photo folder; otherwise both pickers start at the path already in the field, or at the home folder.
- The server has two new endpoints, both under `/api/` and so behind the same protections as the rest (127.0.0.1 only, `Host` check, start-up token; see ADR 0004):
  - `GET /api/folders?path=…` returns the folder's path, parent, the home folder, drive roots, and the names and paths of its visible sub-folders. Files are never listed and nothing is read from inside files. Hidden folders (dot folders, Windows hidden/system) are skipped.
  - `POST /api/mkdir` creates one new folder with `os.mkdir`. The name may not be `.`, `..`, end with `.`, or contain `/ \ : * ? " < > |` or control characters, so it cannot reach outside the chosen parent. This is the only new write.
- Errors such as a folder with no read permission come back as a Chinese message shown in the dialog; the dialog stays on the last folder that worked.
- Existing output-folder rules (outside the input folder, empty or written by this tool before) are unchanged and still checked when copying.

## Alternatives

- The operating system's native folder dialog (tkinter `askdirectory`, AppleScript, PowerShell): looks familiar, but opens behind the browser window on some systems, needs Tk which is missing from some Python installs (Homebrew, many Linux distributions), and needs different code per system.
- The browser's directory upload input: does not expose the full path, and would upload file contents into the page.
- Limiting browsing to the home folder: photos are often on an external drive (`/Volumes/…`, `D:\`), so the owner would lose access to them.

## Consequences

Anyone holding the start-up token can list folder names on this computer, the same reach the scan endpoint already had. The folder list does not show photo counts (optional in the spec); that can be added later if useful.
