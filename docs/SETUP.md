# 設定

這個 repo 用同一套流程：你用白話寫 Issue，Claude 寫規格和程式，Codex 只做審查，GitHub Actions 跑測試，最後由你驗收並合併。

## 已經設定好的

- **Repo**：[aureviaeu/claude-codex-lab](https://github.com/aureviaeu/claude-codex-lab)
- **標籤**（名稱就是這些，不要改）：`proposed`、`ready`、`in-progress`、`needs-human`、`acceptance`、`blocked`、`P0`、`P1`
- **`main` 分支保護**
  - 必須透過 Pull Request 才能合併（不允許直接推上 `main`）
  - 必要狀態檢查是 `test`，而且分支必須是最新的（Require status checks to pass：`test`；Require branches to be up to date before merging）
  - 所有審查對話都必須先解決（Require conversation resolution before merging）
  - 不必等任何人按 Approve（required approving reviews 是 0）

CI 的 job 名稱是 `test`（`.github/workflows/ci.yml`），這是必要檢查。`.github/workflows/resolve-threads.yml` 的 job 名稱是 `resolve-thread`，只負責把討論標成已解決，不是必要檢查。

## 設定 Claude 排程任務

這是 research preview。需要 Claude **Pro、Max 或 Team** 方案。

Claude 跑在 Anthropic 的雲端，那裡擋 GitHub GraphQL，所以 `gh pr` 和 `gh issue` 不能用。任務提示詞已經規定只用 REST。

1. 打開 [claude.ai/code/routines](https://claude.ai/code/routines)。
2. 若還沒接 GitHub，安裝 **Claude GitHub App**，並授權 `aureviaeu/claude-codex-lab`。
3. 選 **New task**。
4. 選這個 repo。
5. 觸發器開兩個：
   - GitHub 事件：**Issue labeled**
   - 排程：**hourly**（每小時）
6. 提示詞貼上 [docs/claude-routine-prompt.md](claude-routine-prompt.md) 程式碼區塊裡的英文，整段、不要改字。

## 設定 Codex 審查

需要 **ChatGPT Plus 或更高**方案。Codex 只審查，不改程式。它讀的是 `AGENTS.md` 裡的 `## Code Review Rules`，只留 P0／P1。

1. 打開 [chatgpt.com/codex](https://chatgpt.com/codex)。
2. 連接 GitHub，授權這個 repo。
3. 進入 **Settings > Code review**。
4. 為這個 repo 打開 **Automatic review**。
5. 在 **Personal preferences** 也打開 **Automatic review**。

不要下 `@codex fix this`、`@codex implement`、`@codex address comments` 或其他 `@codex` 指令。唯一會出現的是 Claude 修完後貼一次的 `@codex review`。

## 每天怎麼用

1. 用 **Idea** 表單開 Issue，用白話寫想法。標題會帶 `[Idea] `，並自動加上 `proposed`。
2. Claude 把內文改寫成規格（目標、範圍、驗收條件），並留言請你加上 `ready`。這一步不寫程式。
3. 你看過規格，同意就加上 `ready`。
4. Claude 改成 `in-progress`，從 `main` 開 `claude/issue-<編號>-<簡稱>`，寫程式並開 PR。
5. CI 跑 `test`。Codex 自動審查，只留嚴重問題（P0／P1）。
6. 有問題時，Claude 修正後在該討論回覆 `[claude-fixed]` 或 `[claude-declined]`。這個回覆會讓 Action 把討論標成已解決，Claude 再貼一次 `@codex review`。
7. CI 綠燈、每則意見都有回覆之後，Claude 拿掉 `in-progress`、加上 `acceptance`，留下給你的驗收清單，然後停下。它不會自己合併。
8. 你照驗收清單看過，滿意再合併。
9. 看到 `needs-human` 就是在等你：規格不清楚、要金鑰或權限、同一種 CI 失敗修了三次、或 Claude 不同意某個 P0。你決定並留言後，拿掉 `needs-human`，Claude 才會繼續。

標成 `blocked` 或 `acceptance` 的項目，Claude 會跳過。
