# 第 3 階段：推薦對話

目標：使用者用口語描述旅行規劃，系統追問缺漏、給出推薦、接受調整，流程與原型相同；有給陌生人試用所需的防護；前端有對話頁。

依據：原型 `agent/extract.py`、`agent/graph.py`、`agent/narrate.py`、`agent/pg_checkpoint.py`、`llm.py`、`web/app.py` 的 `/api/chat`、`web/sessions.py`、`web/warmup.py`、`web/static/`，以及原型 `CLAUDE.md`「慣例與陷阱」「效能」。

## 原型的陷阱（移植時要保留）

- `interrupt()` 所在節點恢復時會從頭重跑，它之前不能有副作用
- 要存進檢查點的自訂型別，必須登記到 serializer 的 `allowed_msgpack_modules`
- Gemma 4 預設會思考（慢約 12 倍），抽欄位一律關掉 reasoning
- LLM 只寫 3–5 句摘要（輸出上限 300 token），明細用模板；整篇讓 LLM 重寫曾經要 30 秒以上
- `OLLAMA_KEEP_ALIVE`：ChatOllama 吃字串，OllamaEmbeddings 只吃整數秒
- 未知目的地一律當成日本／歐美（較嚴格門檻），並標 `region_assumed`
- 多人時假設第一位旅客是租車駕駛，輸出要明說

## 步驟

### 1. LLM 層

把原型 `llm.py` 的 keep_alive、reasoning 開關、「服務暫時不能用」的錯誤分類併進 `app.core.llm`，設定加進 `app.core.config` 與 `.env.example`。抽欄位用 structured output 取得 `TripProfilePatch`，失敗時走原型的機械式後備。

完成條件：移植 `tests/test_llm.py`、`test_extract.py`，全部用 fake model 通過。

### 2. 對話圖

移植 `graph.py`（understand → check_missing → ask（interrupt）→ recommend，`MAX_ASKS=3`，`follow_up` 調整）。檢查點用 `langgraph-checkpoint-postgres` 存在同一個資料庫，連線字串由 `app.core.config` 產生（psycopg 格式，不是 SQLAlchemy URI）。

檢查點的資料表由 saver 的 `setup()` 建立，不歸 Alembic 管：在 `backend/app/alembic/env.py` 用 `include_object` 排除它們，否則 `make migration` 會產生刪表的 migration。

backend 啟動時清掉所有舊對話（原型的隱私設計：session 壽命在記憶體，舊檢查點不該留下使用者輸入）。

完成條件：移植 `tests/test_graph.py`、`test_pg_checkpoint.py`、`test_narrate.py` 的 LLM 部分（用 fake extractor／narrator），在測試資料庫通過；`make migration m="check"` 不產生任何變更。

### 3. `/api/v1/chat` 與防護

移植 `web/app.py` 的對話端點與 `web/sessions.py`。原型的防護全部保留：

- 同時處理數上限，排太久回 503
- 每來源限流（正式環境在 Caddy 後面，來源 IP 取 `X-Forwarded-For` 最後一段）
- 可選的存取碼（`ACCESS_CODE`）與 `/api/v1/verify`，驗證失敗也限流
- 錯誤訊息不外洩內部細節；log 不留使用者輸入
- 訊息長度上限 300 字、`session_id` 格式檢查

LLM 服務錯誤一律回 503 與給使用者看的訊息。

完成條件：移植 `tests/test_web.py` 的對話與防護案例，全部通過。

### 4. 前端對話頁

依原型 `web/static/` 的流程做 React 頁面：對話、追問、推薦卡片（價格、保額、比最低需求多保的項目、條款警示與條文、出處）、調整。現在的健康狀態頁移到 `/health`，並同步修改 `frontend/e2e/smoke.spec.ts` 的路徑。MSW 加上對話端點的假資料。

完成條件：`VITE_MOCK=true` 下能走完一輪追問到推薦；新增 e2e：輸入完整旅行規劃後看到推薦卡片（後端用 fake LLM 時不穩定的部分，改測追問流程）。

### 5. 真模型手動驗收

服務用 Ollama（gemma4:e4b、bge-m3）開著，原型網頁版也開著（`docker compose -f docker-compose.web.yml up -d --build`，http://localhost:8080），對兩邊送同樣 5 段對話（涵蓋缺天數、多人含租車、要求保障高一點、改成含法傳）。

完成條件：每段對話兩邊推薦的費率表與總價相同；不同的逐一記錄原因，寫進 PR 說明。

## 不做

- 方案問答（第 4 階段）、選這個按鈕（第 5 階段）
