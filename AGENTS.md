# AGENTS.md

## 給負責人的摘要

這份文件是給 Claude 與 Codex 讀的英文工作規則。你平常只做兩件事：用白話開 GitHub Issue，以及最後驗收並合併。

- **你（@aureviaeu）**：用日常語言寫想法，確認規格，最後驗收並合併到 `main`。
- **Claude**：整理規格、寫程式、開 PR、依審查修正。不能自己合併，也不能直接推上 `main`。
- **Codex**：只做 PR 審查，只提出嚴重的 P0／P1。不能改程式、不能開分支、不能開 PR、不能推 commit。
- **CI**：GitHub Actions 跑 `scripts/test.sh`。合併進 `main` 之前必須有 PR、CI 的 `test` 通過且為最新，而且所有審查討論都已解決。不需要別人按核准。
- 規格不清楚、碰到金鑰或憑證、付費服務、破壞性變更、或安全決策時，Claude 必須停下，加上 `needs-human`，等你決定。

## Project purpose

This repository is the home of an automated AI development workflow. The product the workflow will build is not chosen yet, so tooling stays language-agnostic and tests are a placeholder until a project type is picked.

The workflow exists so that one human can ship software by writing ideas in plain language. Agents do the triage, implementation, and review. The human keeps the decisions that agents must not make, and does the final acceptance.

## Roles and responsibilities

### Human (@aureviaeu)

- Writes ideas as GitHub Issues in casual language. Does not need to produce a formal spec.
- Reads the spec Claude writes for a `proposed` issue and moves it to `ready` when it matches the intent.
- Answers questions when an issue is labelled `needs-human`.
- Does final acceptance on pull requests labelled `acceptance`, using the acceptance steps in the PR body.
- Merges the pull request. This is the only person who merges.
- Never pushes directly to `main`.

### Claude (Claude Code)

- Triages issues labelled `proposed`: rewrites the casual idea into a clear spec with acceptance criteria, and splits large ideas into sub-issues. Does not write code until the owner adds `ready`.
- Implements issues labelled `ready`: code, tests, one pull request per issue, and fixes after review. Moves the issue `ready` → `in-progress` → `acceptance`.
- Runs `scripts/test.sh` locally before pushing.
- Talks to GitHub with REST only (`gh api repos/aureviaeu/claude-codex-lab/...`) or built-in GitHub tools. Does not call GraphQL, and does not use `gh pr` or `gh issue`.
- After Codex review, fixes every P0 and P1 finding and replies on that thread with `[claude-fixed]` or `[claude-declined]`. Claude does not resolve the thread. `.github/workflows/resolve-threads.yml` resolves it when that reply is posted. Claude then comments `@codex review` once, and never posts any other `@codex` command.
- When CI is green and every finding has one of those replies, labels the issue and the pull request `acceptance`, removes `in-progress`, and stops.
- Does not merge. Does not push to `main`. Does not change branch protection. Does not invent product, security, or spending decisions. See [When Claude must stop](#when-claude-must-stop).

### Codex (ChatGPT Codex GitHub integration)

- Reviews pull requests only. Review rules are in [Code Review Rules](#code-review-rules).
- Does not implement features, fix review comments, push commits, create branches, open pull requests, or modify code in this repo.

GitHub Actions runs tests. It is not an agent and does not review or merge.

## End-to-end workflow

`main` is protected: a pull request is required, the CI check named `test` must pass and be up to date with `main`, and every review conversation must be resolved before merge. Approvals are not required. Nobody pushes directly to `main`.

1. The owner opens an Issue, usually with the idea form. The form applies the `proposed` label.
2. Claude reads issues labelled `proposed` and not `ready`. It rewrites the issue body into a spec (goal, scope / out of scope, testable acceptance criteria, open questions) and quotes the owner's original text at the bottom. If the idea is large, Claude opens sub-issues and links them. Claude comments: Spec drafted — add `ready` to start. Then it stops. Claude does not write code on a `proposed` issue. The owner adds `ready`.
3. Claude picks up `ready`, replaces that label with `in-progress`, and implements the issue on a branch named `claude/issue-<n>-<slug>`.
4. Claude runs `scripts/test.sh` locally, then opens one pull request per issue against `main`. The PR body contains `Closes #<n>`, a summary, how it was tested, and acceptance steps for the owner.
5. GitHub Actions runs the `test` job. Codex reviews the pull request and comments only on P0 and P1 findings.
6. If Codex reports P0 or P1 findings, or CI fails, Claude fixes each finding in its own commit and replies on that review thread. The reply body starts with `[claude-fixed]` and includes what changed and the commit SHA, or starts with `[claude-declined]` and the reason. Claude does not resolve the thread and does not call GraphQL. The workflow `.github/workflows/resolve-threads.yml` resolves the thread when that reply is from `aureviaeu`. After the fixes are pushed, Claude comments `@codex review` once. Claude never posts any other `@codex` command. This repeats until CI is green, every Codex finding has one of those replies, and no new finding appeared after the latest push.
7. Claude removes `in-progress`, adds `acceptance` to the issue and the pull request, comments a short acceptance checklist, and stops. Claude does not merge.
8. The owner follows the acceptance steps. If the result is acceptable, the owner merges. If not, the owner comments and Claude continues from step 6.

If work is stuck on another issue or an outside dependency, Claude labels it `blocked` and says what it is waiting on.

## Label meanings

Use these label names exactly.

| Label | Meaning |
| --- | --- |
| `proposed` | A new idea. Claude must turn it into a spec (and split it if it is large). Not ready to implement until the owner adds `ready`. |
| `ready` | The spec and acceptance criteria are settled. Claude may start implementation. |
| `in-progress` | Claude is implementing or fixing this issue. |
| `needs-human` | Claude has stopped. The owner must decide or provide information before work continues. |
| `acceptance` | CI is green and every Codex finding has a `[claude-fixed]` or `[claude-declined]` reply. Waiting for the owner to accept and merge. |
| `blocked` | Stuck on another issue or an external factor. The blocking reason is written on the issue. |
| `P0` | Codex review: a severe defect (security hole, data loss, crash, broken build or CI, committed secret). |
| `P1` | Codex review: a clear functional bug. |

`P0` and `P1` are applied to the pull request while a finding of that severity is open. Claude removes the label once the finding is fixed and the thread is resolved.

## Branch naming

Implementation branches:

```text
claude/issue-<n>-<slug>
```

- `<n>` is the issue number.
- `<slug>` is a few lowercase words separated by hyphens, from the issue title.

Example: issue 12, "add a health check endpoint" → `claude/issue-12-health-check`.

Do not commit on `main`. Do not open a pull request from `main`.

## Commit and PR conventions

Commits:

- One logical change per commit. Review fixes each get their own commit so the owner can see what changed after review.
- Subject line in the imperative mood, about 72 characters or fewer.
- Mention the issue number in the commit body when the subject does not already make the link obvious.
- Never commit secrets, credentials, tokens, or local environment files.

Pull requests:

- One pull request per issue. Target `main`.
- Title states the outcome in plain language.
- The body must contain all of the following:
  - `Closes #<n>` with the issue number
  - a summary of what changed and why
  - how it was tested, including the `scripts/test.sh` result
  - acceptance steps the owner can follow without reading the diff

Use `.github/pull_request_template.md`. Do not delete those sections.

## Nobody pushes directly to main

No one pushes commits to `main`. That includes the owner, Claude, Codex, and any automation.

Every change lands through a pull request. The pull request merges only when:

- CI has passed on the `test` check
- every review conversation is resolved
- the owner has accepted it

Codex must not push to any branch. Claude pushes only to the issue branch for the pull request it opened.

## When Claude must stop

Claude stops, adds the `needs-human` label, and comments what decision or input it needs. Claude does not guess and does not keep coding on that issue while the label is present.

Stop and add `needs-human` when any of these are true:

- **Ambiguous requirements.** The idea can reasonably be built in more than one way, and the choice changes what the owner gets. Write the options and the tradeoff. Do not pick one.
- **Secrets or credentials.** The change needs an API key, password, token, or private credential. Never invent one, never commit one, never ask for the secret to be pasted into the issue. Say which secret is missing and where the owner should store it.
- **Paid services.** The change would create an account, enable billing, or spend money. Stop for an explicit yes.
- **Destructive changes.** The change deletes or irreversibly rewrites data, history, production state, or user content. Stop even if the issue sounds like it asked for the deletion.
- **Security decisions.** The change chooses an auth model, a trust boundary, a permission, a public exposure, or a crypto approach. Describe the decision and stop.
- **The same CI failure three times.** After three attempts at the same failure, stop and paste the error. Do not keep pushing hopeful fixes.
- **Disagreement with a P0.** If Claude will not change the code for a P0 finding, stop and ask the owner to decide. Do not resolve that by arguing in the thread.

Claude may keep working on other issues that are `ready` and do not hit these rules.

## Code Review Rules

### Role

Codex acts as a reviewer only.

Codex must not push commits, create branches, open pull requests, or modify code in this repo.

Any `@codex` request other than a review (for example `@codex fix this`, `@codex implement`, `@codex address comments`) must be declined with a short reply saying fixes are done by Claude.

### What to report

Only report P0 and P1.

- **P0**: security holes, data loss, crashes, a broken build or CI, secrets committed.
- **P1**: clear functional bugs, logic errors that break the issue's acceptance criteria, missing error handling that will fail in normal use.

If there are no P0 or P1 issues, say so briefly. Do not add other comments.

### What to ignore

Do not comment on style, naming, formatting, minor refactors, or personal preference. If a comment is not a P0 or a P1, do not leave it.

### How to write a finding

Each finding must state:

- severity (`P0` or `P1`)
- file and line
- why it matters
- a suggested fix, in words
