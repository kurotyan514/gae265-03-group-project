# gae265_03_group_project

根據旅行規劃推薦旅遊保險、並依條款回答問題的 SPA。名詞以 [GLOSSARY.md](GLOSSARY.md) 為準。

## 語言

- 所有回答一律用繁體中文
- 軟體用語用台灣用語（例如：程式碼、資料庫、伺服器、設定）
- 專有名詞不翻譯（例如：FastAPI、pgvector、commit、PR、migration）

## Commit

- 先在對話中顯示 commit message 與要 commit 的檔案，使用者確認後才執行
- Message 用繁體中文：title 加 Conventional Commits 前綴（`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`），例如 `feat: 新增 health endpoint`；需要時空一行寫 body
- 一個 commit 只做一件事；commit 前 pre-commit 必須全過，PR 由 CI 把關

## 查詢過去的討論與決策

被問到「當初為什麼這樣做」或過去討論的細節時，依序查：

1. `docs/adr/`：架構與技術決策
2. `GLOSSARY.md`：名詞定義
3. GitHub Issues 的 spec 與 ticket（含已關閉）：`gh issue list --state all --search "<關鍵字>"`，再 `gh issue view <number>`

## Agent skills

### Issue tracker

Issue 與 spec 放在 GitHub Issues，用 `gh` 操作。See `docs/agents/issue-tracker.md`.

### Triage labels

使用預設的五個 triage label。See `docs/agents/triage-labels.md`.

### Domain docs

Single-context：根目錄 `GLOSSARY.md` + `docs/adr/`。See `docs/agents/domain.md`.
