# 0001 Placeholder CI until the project type is chosen

## Context

The product type is not chosen, so there is no language or test runner yet. `main` still requires a pull request and a passing `test` check before merge.

## Decision

CI stays a placeholder. `.github/workflows/ci.yml` runs `scripts/test.sh` in a job whose name is `test`. The script checks that `AGENTS.md` contains `## Code Review Rules`, runs shellcheck on `scripts/` when shellcheck is installed, prints that real tests come later, and exits 0.

## Alternatives

- Add no CI until a stack is chosen. That leaves branch protection with nothing stable to require.
- Pick a language now and generate its test runner. That chooses a stack before there is a product.

## Consequences

A green `test` check means the placeholder passed, not that product behavior was tested. When the project type is chosen, replace the body of `scripts/test.sh` and record that choice in a new ADR. Keep the script path and the job name `test` so the required check does not change.
