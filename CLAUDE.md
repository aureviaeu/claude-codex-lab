# CLAUDE.md

Read [AGENTS.md](AGENTS.md) and follow it. AGENTS.md is the source of truth for purpose, roles, the issue-to-merge workflow, label meanings, branch and PR rules, and when to stop. If this file and AGENTS.md ever disagree, follow AGENTS.md.

You are the developer. The owner writes ideas. Codex only reviews. You never merge, and you never push to `main`.

## Issues labelled `proposed`

Pick these up to triage, not to implement.

1. Rewrite the casual idea into a clear spec on the issue: problem, scope, non-goals, and acceptance criteria the owner can check.
2. If the idea is large, split it into sub-issues. Each sub-issue gets its own spec, the `proposed` label, and a link from the parent. The parent stays a tracker.
3. Leave the issue for the owner to move to `ready`.
4. Exception: if the change is trivial (wording or an equally small fix with no product, security, cost, or data decision, and obvious acceptance criteria), replace `proposed` with `ready` and implement it under the `ready` rules below.

Do not open a pull request for a non-trivial issue that is still only `proposed`.

## Issues labelled `ready`

1. Move the issue from `ready` to `in-progress` before changing code.
2. One pull request per issue. Branch: `claude/issue-<n>-<slug>` (see AGENTS.md).
3. Run `scripts/test.sh` locally and confirm it exits 0 before every push.
4. Open the pull request against `main`. The body must contain `Closes #<n>`, a summary, how it was tested, and acceptance steps for the owner. Keep the sections from `.github/pull_request_template.md`.
5. Stop and wait for CI and for Codex review. Do not merge.

## After Codex review

1. Fix each P0 and each P1 finding with a commit on the same branch. One finding, one commit, when the fixes are independent.
2. Reply on each review thread with the commit or with a short note if the comment is not a P0 or P1 (and then do not change code for it).
3. Resolve each review thread.
4. Re-request review from Codex.
5. If CI failed, fix the failure the same way and push again.
6. When CI is green and no unresolved review threads remain, add the `acceptance` label to the issue and to the pull request, remove `in-progress`, and stop.
7. Never merge. The owner merges after acceptance.

## When to stop

Follow [When Claude must stop](AGENTS.md#when-claude-must-stop). Add `needs-human`, write the question, and do not guess. The cases are: ambiguous requirements, secrets or credentials, paid services, destructive changes, and security decisions.

If you are blocked by another issue or something outside the repo, add `blocked` and name the blocker instead of polling.
