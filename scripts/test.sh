#!/usr/bin/env bash
# Test runner. CI calls `scripts/test.sh` and the GitHub Actions job name
# `test` is the required status check, so do not rename the script or the job.
# Keep the script executable (`chmod +x scripts/test.sh`).
#
# Runs the repository checks, then the Python unit tests in tests/
# (docs/decisions/0002-python-local-web-app.md).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${ROOT}/AGENTS.md" ]]; then
  echo "FAIL: AGENTS.md does not exist"
  exit 1
fi

if ! grep -q '^## Code Review Rules$' "${ROOT}/AGENTS.md"; then
  echo "FAIL: AGENTS.md is missing the heading '## Code Review Rules'"
  exit 1
fi

echo "OK: AGENTS.md exists and contains '## Code Review Rules'"

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

PYTHON="${PYTHON:-python3}"
if ! "${PYTHON}" -c 'from PIL import Image' >/dev/null 2>&1; then
  VENV="${ROOT}/.venv"
  if [[ ! -x "${VENV}/bin/python" ]]; then
    echo "Creating ${VENV} for the test dependencies"
    "${PYTHON}" -m venv "${VENV}"
  fi
  "${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check -r "${ROOT}/requirements.txt"
  PYTHON="${VENV}/bin/python"
fi

echo "Running unit tests with $("${PYTHON}" --version)"
cd "${ROOT}"
"${PYTHON}" -m unittest discover -s tests -t . -v

echo "All tests passed."
