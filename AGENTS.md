# gae265_03_group_project

根據旅行規劃推薦旅遊保險、並依條款回答問題的 SPA。名詞以 [GLOSSARY.md](GLOSSARY.md) 為準。

## 語言

- 所有回答一律用繁體中文
- 軟體用語用台灣用語（例如：程式碼、資料庫、伺服器、設定）
- 專有名詞不翻譯（例如：FastAPI、pgvector、commit、PR、migration）

## 專案地圖

- `backend/app/`：FastAPI 應用，套件名是 `app`（import 寫 `app.xxx`）
  - `api/routes/`：路由；`core/`：設定（`config.py`）、資料庫（`db.py`）、LLM 供應商（`llm.py`）；`models/`：資料表；`alembic/versions/`：migration
- `backend/tests/`：pytest，fixture 在 `conftest.py`
- `frontend/`：Vite + React + TanStack Router，`src/routes/` 是檔案路由；`src/client/` 與 `src/routeTree.gen.ts` 是產生的檔案，不手改；`src/mocks/` 是假資料模式（`VITE_MOCK=true`）；`e2e/` 是 Playwright
- `compose.yaml`：開發環境；`compose.prod.yaml` + `docker/caddy/`：正式環境
- `scripts/doctor.sh`：`make doctor` 的檢查內容

## 硬約束

- Python 套件一律用 uv：backend 依賴 `uv add --package app <pkg>`，開發工具 `uv add --dev <pkg>`
- 前端套件用 pnpm，在本機跑 `pnpm --dir frontend add <pkg>`（`node_modules` 與 frontend 容器共用）
- 資料表繼承 `app.models.BaseTable`（UUID 主鍵 + timezone-aware `created_at`／`updated_at`），並在 `app/models/__init__.py` 匯入，測試與 migration 才看得到
- 測試只連名稱以 `_test` 結尾的資料庫，`app.core.db` 與 `conftest.py` 的保護維持原樣
- 價格、保額與任何數字不由 LLM 產生，流程由程式決定：見 [ADR-0004](docs/adr/0004-llm-never-produces-numbers.md)
- 新增設定：`backend/app/core/config.py` 與 `.env.example` 同步加上（正式環境需要的也加進 `.env.prod.example`）
- Schema 變更：改 model → `make migration m="..."` → 檢查產生的檔案 → `make migrate` → 有影響 API 時 `make client`；已 commit 的 migration 用新 migration 修正
- 路由函式名就是 OpenAPI 的 operationId，也是前端 client 的函式名：整個 app 不可重複（`test_operation_ids_are_unique` 會擋）
- 型別 ignore 寫 `# pyright: ignore[rule]`（`# type: ignore` 不生效）

## 常用指令

跑程式、測試或 migration 前先 `make doctor`，全部 PASS 才繼續（FAIL 附修法，通常是 `make up` 沒開）。完整清單 `make help`。

- `make test`（`make test args="-k xxx"`）、`make e2e`、`make lint`、`make format`
- `make seed`：載入條文 seed 資料（不需要 Azure）；`make ingest`：解析條款 PDF 並重算向量；`make eval-retrieval`：檢索驗收；`make export-seed`：重新產生 seed 檔
- 開發工具頁 `http://localhost:5173/dev`（API 測試台、條文瀏覽；只在非 production 有）
- 服務是 `db`、`backend`、`frontend`、`pgadmin`

服務沒開、改動沒生效、要查 log 或資料庫、需要 `.env` 的設定值時，先讀 `docs/agents/dev-environment.md`。

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
