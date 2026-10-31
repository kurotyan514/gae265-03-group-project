# 第 2 階段：條文庫與混合檢索

目標：16 份富邦險種條款解析成一條一列的條文，連同向量存進 pgvector；用 BM25 加向量的混合檢索查詢條文；推薦的條款警示改查這個條文庫。

依據：原型 `design/2026-10-29-catalog-schema.md`（資料表與匯入規則）、`catalog/`、`rag/keyword.py`、`rag/hybrid.py`、`agent/clauses_check.py`。資料表名稱與主鍵依 D1、D2 的定案。

## 步驟

### 1. 對照資料

在原型產生：

- 每個險種的條文解析結果（`catalog.build` 的輸出：條號、標題、章、頁碼、內文）→ `backend/tests/golden/catalog_rules.json`
- `rag.keyword.tokenize` 對 20 句以上問句的結果、`hybrid.rrf_merge` 對固定排名的結果 → `backend/tests/golden/rag.json`
- 用 bge-m3 對 `backend/data/eval/retrieval_questions.json` 每題呼叫 `catalog.store.search` 的前 5 名（原型的 `db` 要開著且已匯入：`docker compose up -d db`，再跑一次 `python -m insurance_agent.catalog.store`）（險種與條號）→ `backend/tests/golden/vector_top5.json`（只用在第 5 步的人工比對，不進自動測試）

完成條件：16 個險種都有解析結果，條數與 schema 文件第 4 節相符（共 281 條）。

### 2. 資料表與 migration

依 schema 文件建三張表（險種、條文、條文向量）。向量欄位維度讀 `EMBEDDING_DIMENSIONS`（D3），HNSW 索引用 `vector_cosine_ops`。照 `AGENTS.md` 的 Schema 變更流程產生 migration。

完成條件：`make migrate` 成功；`backend/tests/` 有建表與唯一性限制（同險種同條號、同條文同模型）的測試。

### 3. 解析與匯入

移植 `catalog/build.py` 與 `ingest/clauses.py` 用到的解析（`strict_sequence=False`、一條一列、去掉頁首頁尾與備查文號行）到 `backend/app/ingest/`。匯入指令重建這三張表的資料並計算向量，向量文字是「險種名 條文X 標題」接內文。

Makefile 新增 `make ingest`，在 backend 容器裡執行（容器才連得到 Windows 主機的 Ollama）：

```make
ingest: ## 解析條款 PDF 並匯入條文與向量到開發資料庫
	$(COMPOSE) exec -T backend python -m app.ingest.clauses
```

完成條件：

- 解析測試直接讀 `backend/data/clauses/*.pdf`，與 `catalog_rules.json` 逐條相同
- 測試資料庫上用 fake embedding 跑完整匯入，筆數 16／281／281
- 開發資料庫上 `make ingest` 後，用 `docker compose exec -T db` 查到同樣筆數

### 4. 混合檢索

移植 BM25（中文雙字詞）、同義詞展開（`query_synonyms.json`）、RRF（k=60）。BM25 索引從資料庫的條文建在記憶體裡，匯入後要能重建。篩選條件從原型的公司／商品改成險種（可多選）。

完成條件：`rag.json` 對照零差異；用 fake embedding 的檢索測試涵蓋篩選、k 上限、空查詢的錯誤。

### 5. 檢索評估

移植 `rag/evaluate.py` 為 `backend/app/eval/retrieval.py`，Makefile 加 `make eval-retrieval`（同樣在 backend 容器內執行），報告寫到 `docs/reports/retrieval-<日期>-<供應商>.md`。

`retrieval_questions.json` 的期望答案是舊條文庫的公司／商品／條號。改寫成險種與條號時，對應不出來的題目（例如國泰的題目，見 D4）標記「條文庫未收錄」，不自己編造期望答案；不確定的請使用者確認。

完成條件：報告列出每題結果、命中率、與原型 `vector_top5.json` 的差異，以及已知缺口（原型的 q01、q09）。不為了數字調整驗收規則。

### 6. 條文 API

| 路徑 | 用途 |
| --- | --- |
| `GET /api/v1/insurances` | 險種清單與條數 |
| `GET /api/v1/insurances/{code}/rules` | 某險種全部條文 |
| `GET /api/v1/insurances/{code}/rules/{article_no}` | 單一條文，沒有回 404 |
| `POST /api/v1/rules/search` | 混合檢索，回原文、分數與出處（險種、條號、頁碼）；原文不經 LLM |

完成條件：每條路徑都有 API 測試；`make client`、`make typecheck` 通過。

### 7. 條款警示

`agent/clauses_check.py` 用 `config/plan_products.json` 把費率表對應到舊商品名。改成對應到險種之前，先確認組員的方案與險種對應（原型 schema 文件「方案由其他人處理」）是否已經有了：

- 有：用那份對應
- 沒有：請使用者提供對應表，不自己推測

國泰的方案依 D4 處理。第 1 階段 `build_recommendation` 的假警示函式換成這個實作。

完成條件：移植原型 `tests/test_clauses_check.py`，條款不明確時保留方案、加警示並附條文的案例都通過。

## 不做

- 舊條文庫（`chunks.jsonl`）與國泰條款（D4 另開階段）
- 條文內文的硬換行清理（原型 schema 文件「尚未做」，另開 issue）
