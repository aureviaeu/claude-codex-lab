#!/usr/bin/env bash
# Placeholder test runner.
#
# How to replace this file:
# When the project type is chosen, replace the checks below with the real
# test command and keep this path. CI calls `scripts/test.sh` and the GitHub
# Actions job name `test` is the required status check, so do not rename the
# script or the job. Examples of what the body might become:
#   npm test
#   pytest
#   go test ./...
#   cargo test
# Keep the script executable (`chmod +x scripts/test.sh`).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${ROOT}/AGENTS.md" ]]; then
  echo "FAIL: AGENTS.md does not exist"
  exit 1
fi

if ! grep -q '^## Review guidelines$' "${ROOT}/AGENTS.md"; then
  echo "FAIL: AGENTS.md is missing the heading '## Review guidelines'"
  exit 1
fi

echo "OK: AGENTS.md exists and contains '## Review guidelines'"

if command -v shellcheck >/dev/null 2>&1; then
  echo "Running shellcheck on scripts/"
  shopt -s nullglob
  scripts=( "${ROOT}"/scripts/*.sh )
  if ((${#scripts[@]} == 0)); then
    echo "No shell scripts found under scripts/"
  else
    shellcheck "${scripts[@]}"
  fi
else
  echo "shellcheck is not installed; skipping shell lint"
fi

echo "Placeholder tests passed. Real tests will be added once the project type is chosen."
exit 0
