# insurance_agent 移植計畫

把原型 `insurance_agent`（`/mnt/c/project/insurance_agent`，下稱**原型**）的功能移植進本 repo，成為團隊產品。原型之後只當唯讀參考。

這份計畫給在本 repo 執行的 Claude Code 讀。一個 session 只做一個階段：讀完這份 README，再讀該階段的檔案。

## 怎麼開始一個階段

```bash
cd ~/projects/gae265_03_group_project
git switch main && git pull --ff-only
git switch -c migrate/phase-<N>-<簡稱>
claude --add-dir /mnt/c/project/insurance_agent
```

開場提示：「照 `docs/migration/insurance-agent/README.md` 做第 N 階段」。

## 移植規則

1. **原型唯讀。** 不修改、不 commit `/mnt/c/project/insurance_agent` 裡的任何檔案。要在原型跑東西時（例如產生對照資料），把腳本寫在本 repo 外的暫存目錄，用 `cd /mnt/c/project/insurance_agent && docker compose run --rm -T app python - < <腳本>` 執行。
2. **移植的是行為，不是程式碼。** 程式碼改寫成本 repo 的寫法：`AGENTS.md` 的硬約束、`app.core.llm` 取得模型、`app.core.config` 讀設定、SQLModel + Alembic、async 路由。原型的 `docker compose run` 指令、`requirements*.txt`、Python 3.12 的寫法都不沿用。
3. **用 `GLOSSARY.md` 的名詞。** 原型的「旅平險」「產品」等用語，在新程式碼、API 與畫面上改用 GLOSSARY 的詞。GLOSSARY 還沒定義的名詞（例如方案、險種），等第 0 階段的決策 D1 定案。
4. **對照測試是驗收主軸。** 確定性的部分（報價、需求合併、門檻、數字白名單、條文解析、BM25、RRF）要先在原型產生固定輸入的輸出，存成 `backend/tests/golden/*.json`，新實作逐筆比對到完全一致。不一致時先查原因、回報使用者，不改對照資料去配合新程式。
5. **TDD**：先移植或寫會失敗的測試、確認紅燈，再寫實作。原型的測試是第一份待移植清單。
6. **每個階段一個 PR**，照 `AGENTS.md` 的 Commit 規則。階段內可以多個 commit。
7. **原型的鐵則照搬**（第 0 階段寫進 ADR-0004）：價格與保額由程式算、流程由程式決定、LLM 文字過數字白名單、條款不明確時保留方案並附條文、費率表不進向量庫、資料有疑慮不猜。

## 決策點

以下要在第 0 階段由使用者（必要時與組長）定案，結果寫進 `docs/adr/` 或 `GLOSSARY.md`。後面的階段依定案執行；還沒定案的，階段開始前先問使用者。

| # | 問題 | 建議 |
| --- | --- | --- |
| D1 | GLOSSARY 把「險種」列為 Avoid，也沒有定義「方案」；原型的條文 schema（與組長確認過）卻以險種（insCode，例如 T068）為單位，上面還有方案（A～F）| 用 `/domain-modeling` 補定「保險商品／方案／險種」的關係後再命名資料表 |
| D2 | `AGENTS.md` 要求資料表繼承 `BaseTable`（UUID 主鍵），原型 `insurance.id` 卻直接用 insCode（文字）、條文用 serial | 照 `BaseTable`，另加 `code`（insCode，unique）；`plan_insurance` 由其他組員處理，FK 指向 UUID 要先跟組長講好 |
| D3 | 向量維度：原型 bge-m3 是 1024 維，本 repo 的 fake embedding 是 1536 維，正式環境用 Azure OpenAI | 新增設定 `EMBEDDING_DIMENSIONS=1024`：Ollama 用 bge-m3，Azure 用 text-embedding-3-large 並指定 `dimensions=1024`，fake 跟著設定走；兩種供應商的檢索評估分開跑、分開記錄 |
| D4 | 國泰的條款 PDF 已從原型 `docs/` 移除，現在條文庫只有富邦 16 個險種；費率表仍含國泰 | 國泰方案照常報價，條款警示標「條款未收錄，請向保險公司確認」；要收錄就從原型 git 歷史取回 PDF，另開階段 |
| D5 | 費率表要放 JSON 還是資料庫 | 先讀 repo 內的 JSON（原型認定 JSON 是逐格對照 PDF 的來源）；後台需要編輯費率時再匯入 DB |
| D6 | MCP Server 掛在哪裡 | 掛進 backend 的 `/api/mcp`（streamable HTTP），正式環境沿用 Caddy 既有的 `/api/*` 轉送，不用改 Caddyfile |
| D7 | 後台的存取控制：原型只綁 127.0.0.1，正式環境在公開的 VM 上 | 第 7 階段先做唯讀頁面，用 `ADMIN_TOKEN` 標頭保護；正式的登入另開 ADR |

## 階段

每個階段的完成條件都要全部達成，`make test`、`make lint` 全綠，才開 PR、進下一階段。

| 階段 | 檔案 | 內容 | 依賴 |
| --- | --- | --- | --- |
| 0 | [phase-0-prepare.md](phase-0-prepare.md) | 決策定案、ADR-0004、新增套件、資料搬進 repo、.env 切到原型的模型 | — |
| 1 | [phase-1-pricing.md](phase-1-pricing.md) | 報價與推薦的確定性核心（純函式，不碰 DB 與 LLM） | 0 |
| 2 | [phase-2-catalog-rag.md](phase-2-catalog-rag.md) | 條文進 pgvector、BM25 + 向量混合檢索、條文查詢 API、條款警示 | 0 |
| 3 | [phase-3-chat.md](phase-3-chat.md) | LangGraph 推薦對話、`/api/v1/chat`、防護機制、前端對話頁 | 1、2 |
| 4 | [phase-4-qa.md](phase-4-qa.md) | 方案問答 `/api/v1/ask` 與 14 題驗收 | 2 |
| 5 | [phase-5-selections.md](phase-5-selections.md) | 選定方案記錄、匿名身分、刪除我的資料 | 3 |
| 6 | [phase-6-mcp.md](phase-6-mcp.md) | MCP Server（四個唯讀工具） | 3、4 |
| 7 | [phase-7-admin.md](phase-7-admin.md) | 後台（唯讀） | 2 |
| 8 | [phase-8-deploy.md](phase-8-deploy.md) | 正式環境：資料匯入、Azure 上的評估 | 全部 |

第 1 與第 2 階段、第 4 與第 5 階段互不依賴，可以分給不同組員同時做。每個有前端的階段，先完成後端 API、跑 `make client`，前端頁面與 MSW 假資料（`frontend/src/mocks/`）就能交給其他組員平行開發。

## 模組對照

原型路徑都相對 `src/insurance_agent/`。新位置是建議，實際以該階段的 PR 為準。

| 原型 | 新位置 | 階段 |
| --- | --- | --- |
| `pricing/tables.py`、`pricing/quote.py`、`ingest/rates_schema.py` | `backend/app/domain/pricing/` | 1 |
| `agent/profile.py`、`regions.py`、`requirements.py`、`recommend.py` | `backend/app/domain/recommend/` | 1 |
| `agent/narrate.py` 的模板、出處、數字白名單 | `backend/app/domain/recommend/narrate.py` | 1 |
| `catalog/build.py`、`ingest/clauses.py` 的 PDF 解析 | `backend/app/ingest/` | 2 |
| `catalog/store.py`、`catalog/repo.py` | `backend/app/models/`（資料表）＋ `backend/app/domain/rag/`（查詢） | 2 |
| `rag/keyword.py`、`rag/hybrid.py` | `backend/app/domain/rag/` | 2 |
| `rag/evaluate.py` | `backend/app/eval/retrieval.py` | 2 |
| `agent/clauses_check.py` | `backend/app/domain/recommend/` | 2 |
| `catalog/app.py` | `backend/app/api/routes/insurances.py` | 2 |
| `llm.py`（keep_alive、Gemma `reasoning=False`、服務錯誤分類） | 併入 `backend/app/core/llm.py` | 3 |
| `agent/extract.py`、`agent/narrate.py` 的 LLM 部分、`agent/graph.py`、`agent/pg_checkpoint.py` | `backend/app/domain/chat/` | 3 |
| `web/app.py` 的 `/api/chat`、`web/sessions.py`、`web/warmup.py` | `backend/app/api/routes/chat.py`、`backend/app/core/` | 3 |
| `web/static/` | `frontend/src/routes/` | 3–5 |
| `agent/qa.py`、`agent/qa_eval.py` | `backend/app/domain/qa/`、`backend/app/eval/qa.py` | 4 |
| `web/selections.py` | `backend/app/models/`、`backend/app/api/routes/selections.py` | 5 |
| `mcp_server/` | `backend/app/mcp/` | 6 |
| `admin/` | `frontend/src/routes/admin/` ＋ 唯讀 API | 7 |
| `data/rates/*.json`、`config/*.json`、`docs/*.pdf`、`tests/eval/*.json` | `backend/data/`（Dockerfile 只複製 `backend/`，資料要在這裡才會進 image） | 0 |

## 不移植

留在原型、不搬過來：

- Chroma（`rag/vector.py`）、Azure AI Search（`rag/azure_search.py`）、舊的 `clauses` 向量表（`rag/pgvector_store.py`）：ADR-0002 定案用 pgvector 的條文表
- 檢索實驗（`rag/experiments.py`、`ingest/chunk_variants.py`）：只帶結論，`design/research/` 的比較結果在第 0 階段摘要進 ADR
- 費率 PDF 轉 JSON 的工具（`ingest/cathay_rates.py`、`fubon_rates.py`、`fubon_data.py`、`fubon_pages.py`、`rates_report.py`）：JSON 已是成品，要重轉時回原型做
- `pricing/pg_rates.py`：等 D5 決定費率進 DB 時再做
- NAS／App Service 部署、`Dockerfile*`、`docker-compose*.yml`、`requirements*.txt`、`scripts/build_azure_zip.py`、`smoke.py`、`dist/`

## 原型的參考文件

- 鐵則與陷阱：原型 `CLAUDE.md`（「鐵則」「慣例與陷阱」「效能」三節）
- 設計：原型 `design/2026-10-25-travel-insurance-agent-design.md`、`design/2026-10-28-next-features-spec.md`、`design/2026-10-29-catalog-schema.md`
- 已知缺口與待辦：原型 `design/plans/2026-10-29-step5-recommendation.md` 檔尾「剩餘待辦」、`design/plans/2026-10-29-qa-eval-results.md`
