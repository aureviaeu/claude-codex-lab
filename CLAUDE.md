# CLAUDE.md

Read [AGENTS.md](AGENTS.md) and follow it. AGENTS.md is the source of truth for purpose, roles, labels, branch and PR rules, and when to stop. If this file and AGENTS.md disagree, follow AGENTS.md.

You are the developer. The owner writes ideas. Codex only reviews. You never merge, you never push to `main`, and you never change branch protection.

The scheduled task prompt is [docs/claude-routine-prompt.md](docs/claude-routine-prompt.md). Each run, act idempotently: inspect the current state, do the next step, then stop. Skip anything labelled `needs-human`, `blocked`, or `acceptance`.

## GitHub access

GitHub GraphQL is blocked in the scheduled-task environment, including `gh pr` and `gh issue`.

Use built-in GitHub tools, or REST only:

```text
gh api repos/aureviaeu/claude-codex-lab/...
```

Do not call GraphQL. Do not run `gh pr` or `gh issue`.

Useful REST paths (all under that prefix):

- Issues and labels: `issues/<n>`, `issues/<n>/labels`, `issues/<n>/comments`
- Pull requests: `pulls`, `pulls/<n>`, `pulls/<n>/comments`, `pulls/<n>/reviews`
- Reply in a review thread: `pulls/<n>/comments/<comment_id>/replies`

## Issues labelled `proposed`

Pick these up to write a spec, not to implement. Ignore the issue if it is also labelled `ready`.

1. Rewrite the issue body into a spec: Goal, Scope / Out of scope, Acceptance criteria (a testable checklist), Open questions.
2. Keep the owner's original text quoted at the bottom.
3. If the idea is too large for one change, split it into sub-issues. Each sub-issue gets the same kind of spec and the `proposed` label. Link them from the parent.
4. Comment exactly: Spec drafted — add `ready` to start.
5. Stop. Do not write code.

## `ready` → `in-progress` → `acceptance`

1. An issue labelled `ready` with no open pull request: add `in-progress` (remove `ready`), create `claude/issue-<n>-<short-slug>` from `main`, implement, add or adjust tests, and run `scripts/test.sh` locally before pushing.
2. Open one pull request against `main`. The body must contain `Closes #<n>`, a summary, how each acceptance criterion is met, and acceptance steps for the owner. Keep the sections from `.github/pull_request_template.md`.
3. Wait for CI and for Codex. Do not merge.

## After Codex review

For each Codex P0 or P1 finding that does not already have a reply:

1. Fix it, or decide it is not a defect. One finding, one commit, when the fixes are independent. Push the fix before you reply.
2. Reply in that review thread. The body starts with one of these:
   - `[claude-fixed] <what changed> (<sha>)`
   - `[claude-declined] <reason>`
3. That reply auto-resolves the thread. `.github/workflows/resolve-threads.yml` does it when the reply is from `aureviaeu`. Do not try to resolve the thread yourself.
4. If CI fails, fix the failure and push.
5. After pushing fixes, comment `@codex review` once on the pull request. Never post any other `@codex` command (`@codex fix this`, `@codex implement`, `@codex address comments`, and anything else are forbidden).

When CI is green, every Codex finding has a `[claude-fixed]` or `[claude-declined]` reply, and no new finding appeared after the latest push: remove `in-progress`, add `acceptance` to the issue and the pull request, comment a short acceptance checklist for the owner, and stop.

## When to stop

Add `needs-human`, comment exactly what decision is needed, and stop. Do not guess.

- Ambiguous or unclear requirements. Write the options. Do not pick one.
- Secrets, credentials, or missing permissions. Never invent a secret, never commit one, and never ask for it to be pasted into the issue.
- Paid services. Stop for an explicit yes before spending money or enabling billing.
- Destructive changes to data, history, or production state.
- Security decisions (auth, trust boundary, permissions, exposure, crypto).
- The same CI failure after 3 attempts. Paste the error.
- Disagreement with a P0. Do not keep arguing, and do not paper over it with `[claude-declined]`.

If you are blocked by another issue or something outside the repo, add `blocked` and name the blocker.

The owner merges. You do not.
