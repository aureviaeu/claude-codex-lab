# 0005 Re-applying an order to the output folder is all-or-nothing

## Context

Re-applying an order renames files the tool wrote earlier and copies new ones. The manifest maps each file's content hash to its output name. If a copy or a write failed part-way (a source removed after the scan, a full disk), files had already been renamed while the old manifest stayed, so a retry trusted stale names and could output photos in the wrong order (Codex review on #9).

## Decision

- `output.apply` logs every change it makes to the output folder (each rename, and each file it creates).
- New reports and the new manifest are written to temporary names first, the old ones are moved aside, and the manifest is swapped in last.
- On any error the log is undone newest first, so the folder, its reports, and its manifest are exactly as before the run. The owner sees an error saying nothing was changed. If the undo itself fails, the error names the files and asks for a new output folder.
- The moved-aside old reports are deleted only after everything succeeded.

## Alternatives

- Build the whole result in a new staging folder and swap folders: needs copying every file again (slow for large trips) or a directory swap that is not atomic on every platform.
- Record staging state in the manifest and recover on the next run: more state to get right, and the folder stays inconsistent until the next run.

## Consequences

A crash of the whole process (not an exception) part-way can still leave `.travelphotos-tmp-*` files behind. Revisit if that is seen in practice.
