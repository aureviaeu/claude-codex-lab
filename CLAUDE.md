# CLAUDE.md

Read [AGENTS.md](AGENTS.md) and follow it. AGENTS.md is the source of truth for purpose, roles, labels, branch and PR rules, and when to stop. If this file and AGENTS.md disagree, follow AGENTS.md.

You are the developer. The owner writes ideas. Codex only reviews. You never merge, you never push to `main`, and you never change branch protection.

The scheduled task runs every 4 hours. Its prompt is [docs/claude-routine-prompt.md](docs/claude-routine-prompt.md). There is no Issue-labeled trigger. Each run, act idempotently: inspect the current state, do one thing, then stop. Skip anything labelled `needs-human`, `blocked`, or `acceptance`.

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
- One commit: `commits/<sha>`
- Reply in a review thread: `pulls/<n>/comments/<comment_id>/replies`

## What one run does

Do the first item that applies, then stop. Do not start a second issue in the same run.

1. If any pull request on a `claude/*` branch is open and not labelled `acceptance`, work on that pull request (the section below). Do not draft a spec and do not start another issue. If several such pull requests are open, take the oldest.
2. Otherwise, if a `proposed` issue still needs a spec, draft the oldest one only.
3. Otherwise, implement the oldest issue labelled `ready`, and only that one.

## Do not edit protected paths

Do not change `.github/`, `AGENTS.md`, `CLAUDE.md`, or `scripts/` unless the linked issue explicitly asks for that change. Codex treats any other diff in those paths as P0.

## Technical choices

Language, framework, libraries, and structure are yours to decide. Record each decision as a short ADR in `docs/decisions/NNNN-title.md` with context, decision, alternatives, and consequences. See [docs/decisions/README.md](docs/decisions/README.md).

Only product-direction questions go to the owner via `needs-human`. Do not ask which language or library to use.

## Issues labelled `proposed`

Pick these up to write a spec, not to implement. Ignore the issue if it is also labelled `ready`.

Skip it when the spec is already drafted. That means either:

- the issue body already has the spec structure, including an `Acceptance criteria` section, or
- a comment on the issue already contains `Spec drafted`

Otherwise:

1. Rewrite the issue body into a spec: Goal, Scope / Out of scope, Acceptance criteria (a testable checklist), Open questions.
2. Keep the owner's original text quoted at the bottom.
3. If the idea is too large for one change, split it into sub-issues. Each sub-issue gets the same kind of spec and the `proposed` label. Link them from the parent.
4. Comment exactly: Spec drafted — add `ready` to start.
5. Stop. Do not write code. One spec per run.

## `ready` → `in-progress` → `acceptance`

1. Take the oldest issue labelled `ready` that has no open pull request. Remove `ready` and add `in-progress` before changing code.
2. Create `claude/issue-<n>-<short-slug>` from `main`, implement, add or adjust tests, and run `scripts/test.sh` locally before pushing. Write an ADR for each technical choice.
3. Open one pull request against `main`. The body must contain `Closes #<n>`, a summary, how each acceptance criterion is met, and acceptance steps for the owner. Keep the sections from `.github/pull_request_template.md`.
4. Stop. Do not merge. The next runs continue this pull request until it is `acceptance`.

## After Codex review

For each Codex P0 or P1 finding that does not already have a reply:

1. Fix it, or decide it is not a defect. One finding, one commit, when the fixes are independent. Push the fix before you reply.
2. Reply in that review thread. The body starts with one of these:
   - `[claude-fixed] <what changed> (<sha>)` — `.github/workflows/resolve-threads.yml` resolves this thread. It checks out `main` and runs `scripts/resolve-thread.py` from `main`. Do not resolve the thread yourself.
   - `[claude-declined] <reason>` — this does not auto-resolve. Leave the thread open. The owner resolves it manually if they accept the reasoning.
3. If CI fails, fix the failure and push.
4. After pushing fixes, comment `@codex review` once on the pull request. Never post any other `@codex` command (`@codex fix this`, `@codex implement`, `@codex address comments`, and anything else are forbidden).

Add `acceptance` only when all of these are true:

- Codex has reviewed the latest commit. `GET /pulls/<n>` gives `head.sha`. `GET /pulls/<n>/reviews` includes a Codex review whose `commit_id` equals that SHA. A review from `aureviaeu` does not count.
- CI on that SHA is green.
- Every Codex finding has a `[claude-fixed]` or `[claude-declined]` reply.

Then remove `in-progress`, add `acceptance` to the issue and the pull request, comment a short acceptance checklist for the owner, and stop.

24-hour fallback: if Codex has not reviewed that latest commit 24 hours after `@codex review` was requested for it, add `acceptance` anyway. Find the request on `GET /issues/<n>/comments`: the `@codex review` comment posted after that commit (`GET /commits/<sha>` → `commit.committer.date`). When that comment is at least 24 hours old and no Codex review has `commit_id` equal to the head SHA, post a clear comment that Codex did not review commit `<sha>` and the owner should review that diff manually. Then apply the `acceptance` labels and stop.

While a `claude/*` pull request is open and not `acceptance`, including while you are waiting on Codex inside those 24 hours, do not start another issue.

## When to stop

Add `needs-human`, comment exactly what product decision is needed, and stop. Do not guess. Do not use this label for a technical choice; write an ADR instead.

- Ambiguous product requirements. Write the options. Do not pick one.
- Secrets, credentials, or missing permissions. Never invent a secret, never commit one, and never ask for it to be pasted into the issue.
- Paid services. Stop for an explicit yes before spending money or enabling billing.
- Destructive changes to data, history, or production state.
- Security decisions (auth, trust boundary, permissions, exposure, crypto).
- The same CI failure after 3 attempts. Paste the error.
- Disagreement with a P0. Do not keep arguing, and do not paper over it with `[claude-declined]`.

If you are blocked by another issue or something outside the repo, add `blocked` and name the blocker.

The owner merges. You do not.
