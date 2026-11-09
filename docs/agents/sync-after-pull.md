# 拉取最新 main 之後：同步資料庫、seed 與檢查

給 AI 助手看的操作手冊：使用者說「更新 main」「同步一下」「環境壞了」或剛合併過別人的 PR 時，照這份做。先讀 [dev-environment.md](dev-environment.md)（服務由使用者的終端機持有、`.env` 的規則）。

## 原則

- 先備份、再更新；每一步失敗就停下來回報，不要硬往下。
- 不改使用者的 `.env`（也不要讀它的值）；缺什麼變數就告訴使用者要加什麼。
- 破壞性操作（`docker compose down -v`、清資料表、`git reset --hard`、`git push --force`）要使用者明確同意才做。
- `frontend/src/client/`、`routeTree.gen.ts` 是產生檔，不手改；已 commit 的 migration 不改，要修就寫新的。

## 1. 備份目前的工作

`git status`。有未 commit 的修改或未追蹤檔案時，用暫時的 index 做備份分支，不動工作目錄：

```bash
IDX=$(mktemp -u); export GIT_INDEX_FILE=$IDX
git read-tree HEAD && git add -A
C=$(git commit-tree "$(git write-tree)" -p HEAD -m "backup: 同步前的工作中版本")
unset GIT_INDEX_FILE; rm -f "$IDX"
git branch "backup/pre-sync-$(date +%Y%m%d-%H%M)" "$C"
```

## 2. 更新

```bash
git fetch origin
git log --oneline HEAD..origin/main      # 看有哪些新 commit
```

- 在 `main` 上：`git pull --ff-only`；其他分支：`git fetch origin main:main`，再問使用者要不要 `git merge main`。
- 有衝突時停下來，列出衝突檔案與建議做法；產生檔（`frontend/src/client/*`）衝突時取任一邊，最後用 `make client` 重新產生。

## 3. 看更新改了什麼，決定要跑哪些指令

```bash
git diff --stat <更新前>..<更新後> -- <路徑>
```

| 改到的路徑 | 要跑 |
| --- | --- |
| `backend/app/alembic/versions/` | `make migrate` |
| `pyproject.toml`、`backend/pyproject.toml`、`uv.lock` | `uv sync` |
| `frontend/package.json`、`pnpm-lock.yaml` | `pnpm --dir frontend install` |
| `backend/data/seed/`、`backend/data/config/`、`backend/app/seed.py` | `make seed` |
| `backend/app/ingest/catalog.py` 的 `embedding_text`（送去算向量的文字） | 已經用網頁入庫、不在 seed 裡的險種要 `make reembed` 重算向量（只換目前 model 的向量，會呼叫 embedding 供應商）；seed 裡的 39 個險種 `make seed` 就會換成新向量 |
| `backend/app/policy/`（保單比對） | `make seed`：比對只讀資料庫的險種保單代碼（`insurance.policy_codes`），沒跑過 seed 就沒有代碼；`config/policy_codes.json` 只是 seed 的初始資料，`make seed` 只補上 JSON 有的代碼，不會蓋掉後台填的 |
| `backend/app/api/`、`backend/app/contracts/`、API 的 schema | `make client` |
| `.env.example`、`.env.prod.example`、`backend/app/core/config.py` | 對照使用者的 `.env` 缺什麼，告訴使用者（不要自己改） |
| `compose.yaml`、`docker/` | 請使用者重開 `make up` |
| `backend/app/contracts/`、`docs/agents/handoff/` | 見下面「契約有更新時」 |

不確定就全跑，順序固定：

```bash
make doctor          # 全部 PASS 才繼續；FAIL 附修法，通常是 make up 沒開
uv sync
pnpm --dir frontend install
make migrate
make seed
make client
make lint && make test
make e2e             # 需要 .env 的 DEV_LOGIN_ENABLED=true，否則會跳過登入相關測試
```

## 4. 驗證資料庫

```bash
# migration 版本要等於最新
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "${POSTGRES_DB:-$POSTGRES_USER}" -tA -c "select version_num from alembic_version"'
(cd backend && uv run alembic heads)
```

`make seed` 成功後的筆數（2026-11-04）：險種 39、條文 677、向量 677、方案保費 399、保障明細 935、保單代碼對照 20、事故類型 9（含「其他」）、待辦範本 31。筆數不對就看 `make seed` 的輸出與 `backend/data/` 有沒有被改到。

## 5. 資料庫壞了或要重做

由輕到重，**先用輕的**：

1. **只重載資料**：`make seed`（重跑結果相同，不會重複）。
2. **條款庫不對**：請使用者同意後，依序刪除指到險種的資料再重載：`message_citation`、`conversation_insurance`、`policy_addon`、`incident_clause`、`rule_embedding`、`insurance_rule`、`insurance`，然後 `make seed`。使用者、保單、事件本體保留。
3. **整個開發資料庫重建**（會清掉所有本機資料，需使用者明確同意）：`docker compose down -v` → 請使用者重開 `make up` → `make doctor` → `make migrate` → `make seed`。

migration 失敗時：貼出錯誤與 `alembic_version`，不要手動改 `alembic_version` 表。

## 6. 契約有更新時

契約 = `backend/app/contracts/`、`IncidentContext`、5/6/7 號的交接說明（`docs/agents/handoff/`）。

1. 讀 [handoff/contract-changelog.md](handoff/contract-changelog.md) 最上面幾筆，和 `git diff <更新前>..<更新後> -- backend/app/contracts docs/agents/handoff`。
2. 你若是 5、6、7 號某個 agent 的實作者，跑契約測試：`CONTRACT_AGENT_5=<你的模組> make test args="-k contracts"`（6 用 `CONTRACT_AGENT_6`，7 用 `CONTRACT_AGENT_7`），確認自己的實作沒被破壞；修自己的程式，**不要改** `contracts/`、`models/`、`domain/incident/`、`api/`。
3. 你若是平台負責人（要改契約或資料表）：
   - 改 model → `make migration m="..."` → 檢查產生的檔案（有資料要搬時手動補 SQL，新欄位 NOT NULL 要給預設值）→ `make migrate` → `make migration m=check` 確認沒有差異後刪掉那個空檔。
   - 改契約欄位盡量只新增、保留舊欄位（例如 `is_done` 保留、新增 `status`），避免破壞別人的實作。
   - 在 [handoff/contract-changelog.md](handoff/contract-changelog.md) 最上面加一筆：改了什麼、舊欄位怎麼辦、還沒做的事。
   - 更新 `docs/agents/handoff/` 裡提到被改欄位的說明、`make client`、`make lint && make test && make e2e`。
   - 通知 5、6、7 號負責人（PR 描述寫清楚「契約變更」與影響）。

## 7. macOS 注意事項

- Docker Desktop 要先開；工具鏈用 `mise install` 對照 `mise.toml`。
- shell 是 BSD 版 `sed`／`date`／`xargs`、舊版 bash 3.2：`sed -i` 要寫 `sed -i ''`，不要用 `date -d`、`grep -P`；能用 `git`／`make`／`docker compose` 就不要自己寫 shell 片段。
- `node_modules` 與前端容器共用：`pnpm install` 後前端容器若報原生模組或權限錯誤，讀 [dev-environment.md](dev-environment.md)，不要自己刪 `node_modules` 或 volume。
- Apple Silicon 若出現 `exec format error`，不要改 compose，回報完整錯誤。
- 連接埠被佔用：`lsof -i :<port>` 找出是誰，回報使用者，不要直接 kill。

## 8. 常見問題

| 症狀 | 原因與修法 |
| --- | --- |
| `ModuleNotFoundError` | 少了依賴：`uv sync` 後重啟 backend 容器（`make up` 開著會自動重建） |
| `relation "xxx" does not exist` | 沒跑 migration：`make migrate` |
| 查不到方案或條文、方案資料是空的 | 沒跑 seed：`make seed` |
| 登入相關 e2e 全被跳過 | `.env` 沒有 `DEV_LOGIN_ENABLED=true`；請使用者加上並重開 `make up` |
| 前端型別錯誤、找不到 API 函式 | `make client` |
| 舊對話查不到條文 | 條款庫重載後對話與險種的關聯被清掉，到 `/dev/chat` 建新對話 |
| `make test` 因本機 `.env` 失敗 | 測試應該不依賴 `.env`；發現時修測試（用 `monkeypatch` 固定設定），不要改 `.env` |
| `make doctor` 的 LLM 連線 FAIL | 沒有 Azure 金鑰時可略過；`make seed`、`make test` 不需要 |

## 9. 做完後回報

回報：更新前後的 commit、跑了哪些指令與結果、migration 版本與 seed 筆數、修了什麼、契約有沒有變更（有的話指到 changelog）、還需要使用者處理的事。
