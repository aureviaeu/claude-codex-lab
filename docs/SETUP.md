# 設定

這個 repo 用同一套流程：你用白話寫 Issue，Claude 每 4 小時做一件事（寫規格或做一個 Issue），Codex 只做審查，GitHub Actions 跑測試，最後由你驗收並合併。

照下面的順序做。上一步沒做完，不要做下一步。

## 已經設定好的

- **Repo**：[aureviaeu/claude-codex-lab](https://github.com/aureviaeu/claude-codex-lab)
- **標籤**（名稱就是這些，不要改）：`proposed`、`ready`、`in-progress`、`needs-human`、`acceptance`、`blocked`、`P0`、`P1`
- **`main` 分支保護**
  - 必須透過 Pull Request 才能合併（不允許直接推上 `main`）
  - 必要狀態檢查是 `test`，而且分支必須是最新的（Require status checks to pass：`test`；Require branches to be up to date before merging）
  - 所有審查對話都必須先解決（Require conversation resolution before merging）
  - 不必等任何人按 Approve（required approving reviews 是 0）

CI 的 job 名稱是 `test`（`.github/workflows/ci.yml`），這是必要檢查。`.github/workflows/resolve-threads.yml` 的 job 名稱是 `resolve-thread`，不是必要檢查。它只在回覆以 `[claude-fixed]` 開頭時，把該討論標成已解決。`[claude-declined]` 不會自動解決，留給你手動關掉。這個 workflow 會 checkout `main`，再執行 main 上的 `scripts/resolve-thread.py`，所以要等這張 PR 合併之後才會生效。

## 1. 先合併這張 PR

把這張 PR 合併到 `main`。在這之前不要建立 Claude 任務，也不要開 Codex 自動審查。合併之後，main 上才有排程要用的規則，以及從 main 執行的解討論腳本。

## 2. 建立 Claude 排程任務

這是 research preview。需要 Claude **Pro、Max 或 Team** 方案。

Claude 跑在 Anthropic 的雲端，那裡擋 GitHub GraphQL，所以 `gh pr` 和 `gh issue` 不能用。任務提示詞已經規定只用 REST。

觸發器只開排程，每 4 小時一次。不要開 Issue labeled，也不要開其他 GitHub 事件。

1. 打開 [claude.ai/code/routines](https://claude.ai/code/routines)。
2. 若還沒接 GitHub，安裝 **Claude GitHub App**，並授權 `aureviaeu/claude-codex-lab`。
3. 選 **New task**。
4. 選這個 repo。
5. 觸發器只留排程：每 4 小時。cron 用 `7 */4 * * *`（每 4 小時的第 7 分）。
6. 提示詞貼上 [docs/claude-routine-prompt.md](claude-routine-prompt.md) 程式碼區塊裡的英文，整段、不要改字。

## 3. 按一次 Run now，先看結果

任務存好之後，按 **Run now** 跑一次。看這次執行有沒有報錯，以及它是否只做了下一件該做的事（例如還沒有 `ready` 的 Issue 時，不該開始寫程式）。結果看起來正常，再做下一步。

## 4. 最後才開啟 Codex 自動審查

需要 **ChatGPT Plus 或更高**方案。Codex 只審查，不改程式。它讀的是 `AGENTS.md` 裡的 `## Code Review Rules`，只留 P0／P1。沒有經過 Issue 要求就改 `.github/`、`AGENTS.md`、`CLAUDE.md` 或 `scripts/`，一律是 P0。

1. 打開 [chatgpt.com/codex](https://chatgpt.com/codex)。
2. 連接 GitHub，授權這個 repo。
3. 進入 **Settings > Code review**。
4. 為這個 repo 打開 **Automatic review**。
5. 在 **Personal preferences** 也打開 **Automatic review**。

不要下 `@codex fix this`、`@codex implement`、`@codex address comments` 或其他 `@codex` 指令。唯一會出現的是 Claude 修完後貼一次的 `@codex review`。

## 每天怎麼用

1. 用 **Idea** 表單開 Issue，用白話寫想法。標題會帶 `[Idea] `，並自動加上 `proposed`。
2. 排程跑到時，Claude 把內文改寫成規格（目標、範圍、驗收條件），並留言請你加上 `ready`。規格已經寫過的 Issue 會跳過。這一步不寫程式。
3. 你看過規格，同意就加上 `ready`。
4. 下一次排程，若沒有尚未驗收的 `claude/*` PR，Claude 只做最舊的那一個 `ready`：拿掉 `ready`、加上 `in-progress`，從 `main` 開分支、寫程式並開 PR。語言和框架由 Claude 決定，並寫進 `docs/decisions/`。
5. CI 跑 `test`。Codex 自動審查，只留嚴重問題（P0／P1）。
6. 有問題時，Claude 修正後在該討論回覆 `[claude-fixed]` 或 `[claude-declined]`，再貼一次 `@codex review`。只有 `[claude-fixed]` 會把討論標成已解決。`[claude-declined]` 留著等你決定；你接受理由就自己把該討論標成已解決。
7. Codex 已經審查最新的 commit、CI 綠燈、每則意見都有回覆之後，Claude 才拿掉 `in-progress`、加上 `acceptance`，留下驗收清單，然後停下。若你貼了 `@codex review` 之後過了 24 小時 Codex 仍沒審該 commit，Claude 仍會標 `acceptance`，並註明你要自己看那個 diff。它不會自己合併。
8. 你照驗收清單看過。`[claude-declined]` 的討論若你接受，就手動解決，然後合併。
9. 看到 `needs-human` 就是在等你的產品決定：規格不清楚、要金鑰或權限、同一種 CI 失敗修了三次、或 Claude 不同意某個 P0。技術選型不會用這個標籤。你決定並留言後，拿掉 `needs-human`，Claude 才會繼續。

標成 `blocked` 或 `acceptance` 的項目，Claude 會跳過。有一張還沒標 `acceptance` 的 `claude/*` PR 時，排程不會另開新的 Issue。
