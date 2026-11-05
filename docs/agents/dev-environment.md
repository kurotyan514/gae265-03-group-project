# 開發環境操作

給 agent 看的開發環境操作規則：服務怎麼啟動、改動怎麼生效、指令在哪裡跑、怎麼查狀態。安裝步驟見 `README.md`，指令清單見 `make help`。

## 服務由使用者的終端機持有

`make up` 是前景執行的 `docker compose up --watch`，會一直佔住終端機，所以由使用者在自己的終端機分頁執行。agent 要用服務時：

1. 先跑 `make doctor`。全部 PASS 就直接用。
2. 服務沒開（`db`、`backend` 等 FAIL）時，請使用者在另一個終端機執行 `make up`，等使用者回報後再跑一次 `make doctor`。
3. 只想看狀態，用 `docker compose ps`。

## 改動怎麼生效

| 改了什麼 | 怎麼生效 | 要做的事 |
| --- | --- | --- |
| `backend/app/**` | compose watch 同步進容器，`fastapi dev` 自動重新載入 | 不用重啟；用 `docker compose logs --tail=50 backend` 確認有重新載入、沒有錯誤 |
| `backend/tests/**` | 不同步進容器，測試在本機跑 | `make test` |
| `backend/pyproject.toml`、`uv.lock` | watch 自動重建 backend image（`make up` 要開著） | 等重建完成再測 |
| `frontend/src/**` | 本機目錄直接掛進容器，Vite HMR | 不用重啟 |
| 前端依賴 | `node_modules` 本機與容器共用，容器不會自己裝 | 在本機 `pnpm --dir frontend add <pkg>`；`docker compose restart frontend` |
| `.env` | 容器只在建立時讀 `.env`，`restart` 不會重讀 | 請使用者按 Ctrl+C 停掉 `make up` 再重跑 |
| model（資料表） | backend 容器啟動時會 `alembic upgrade head`，但不會產生 migration | 照 `AGENTS.md` 的 Schema 變更流程 |

## 指令在哪裡跑

- **本機**（repo 根目錄）：`make test`、`make lint`、`make typecheck`、`make migrate`、`make migration`、`make client`、`uv run ...`。這些指令透過 `localhost:${POSTGRES_PORT}` 連 db 容器，所以至少 `db` 要開著。
- **容器內**：backend 服務本身。要在跟 backend 一樣的環境執行程式碼：`docker compose exec -T backend python -c "..."`。
- 測試固定用 fake LLM 和名稱以 `_test` 結尾的資料庫（`backend/tests/conftest.py`）：不需要 API key，也不會碰到開發資料。

## `.env` 由使用者管理

`.claude/settings.json` 禁止讀寫 `.env`。

- 要知道目前用哪個 LLM 供應商：看 `make doctor` 的「.env 必填項齊全（LLM_PROVIDER=...）」。
- 要查其他非機密設定：`docker compose exec -T backend python -c "from app.core.config import settings; print(settings.<欄位>)"`。key、密碼等機密欄位不印出來。
- 需要改 `.env` 時，告訴使用者要改哪一行、改成什麼，由使用者自己改，再請使用者重跑 `make up`。

## 查狀態與除錯

- **Log**：`docker compose logs --tail=200 <服務>`。`make logs` 會持續追蹤、不會結束，留給使用者自己看。
- **資料庫**：`docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "<SQL>"'`。測試資料庫把 `$POSTGRES_DB` 換成 `"$POSTGRES_TEST_DB"`。
- **API**：`curl -sS "http://localhost:$(docker compose port backend 8000 | cut -d: -f2)/api/v1/health"`；OpenAPI 在同一個 port 的 `/openapi.json`。
- **只做前端、不需要後端**：`cd frontend && VITE_MOCK=true pnpm dev`（MSW 假資料，`src/mocks/`）。

## 改完程式碼的驗證

依序執行，全部通過才算完成：

1. `make test`
2. `make lint`（已包含 `make typecheck`）
3. 改了 API 的 schema：`make client`，再跑一次 `make typecheck`
4. 改了頁面或前後端串接：`make e2e`（服務要開著）

CI（`.github/workflows/ci.yml`）跑的是 `make lint`、`make test` 和 `pnpm build`，本機這幾項通過，PR 才會過。

## Google 登入與授權

決定見 [ADR-0020](../adr/0020-google-login-and-incremental-authorization.md)。自動測試與 e2e 一律不連 Google；平常開發用測試登入（`DEV_LOGIN_ENABLED=true`）與假的 `GoogleAccess`，只有要用真實帳號驗證時才需要下面的設定。

- **Google Cloud 專案**：`gae265-team3-travel-insurance`，OAuth 用戶端是網頁應用程式「gae265-team3-好險有你」，要啟用 Google Drive API 與 Gmail API。開發與正式環境共用這一個專案。
- **OAuth App 維持「測試中」**：只有測試使用者名單上的 Google 帳號能登入，名單由一位指定成員管理。授權 Drive、Gmail 約 7 天後失效，要重新授權。
- **redirect URI**：本機是 `http://localhost:5173/api/v1/auth/google/callback`（瀏覽器走前端的 Vite，`/api` 轉給後端），登入與授權共用。正式環境的網址另外登記在同一個用戶端。
- **`.env` 要有的設定**：`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`PUBLIC_BASE_URL`（本機是 `http://localhost:5173`）、`TOKEN_ENCRYPTION_KEY`（產生方式見 `.env.example` 的註解）。由使用者自己填；agent 不讀、不改 `.env`，缺什麼就告訴使用者。

新成員要用真實帳號驗證時，請使用者自己完成：

1. 請專案擁有者在 Google Cloud Console 的「IAM」把自己加進 `gae265-team3-travel-insurance`。
2. 請管理名單的成員把自己的 Gmail 加進 OAuth 同意畫面的「測試使用者」。
3. 向組員私下取得 client secret（不要放進 git、issue 或聊天紀錄）；找不到時，在用戶端頁面「新增密鑰」產生新的，並通知還在用舊 secret 的組員。
4. 把上面的設定填進自己的 `.env`，停掉 `make up` 再重跑。
5. 照 [handoff/google-login.md](handoff/google-login.md) 的「驗證清單」走一次手動驗證。

## 需要使用者處理的情況

- `make doctor` 顯示 Docker 未啟動：請使用者開 Docker Desktop。
- LLM 供應商連線 FAIL：key、endpoint 或 Ollama 的問題，照 doctor 的提示請使用者修改 `.env` 或啟動 Ollama。
- port 衝突：請使用者改 `.env` 的 `*_PORT`。
- `make db-reset`、`make down`、`docker volume rm` 會清掉資料或停掉使用者的服務。執行前先說明原因和影響，取得同意。
