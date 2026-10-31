# backend/data

從原型 `insurance_agent`（來源版本 `512c7b1`）複製進來的資料。Dockerfile 只複製 `backend/`，資料放這裡才會進 image。檔案與原型的 sha256 完全相同。

| 資料夾 | 內容 | 原型來源 |
| --- | --- | --- |
| `rates/` | 費率表 JSON（富邦 6 份、國泰 2 份） | `data/rates/` |
| `config/` | 地區、門檻、費率表對條款、富邦與中信險種清單（含備查文號，各一份 JSON）、條款勘誤、查詢同義詞 | `config/`（不含 `rag_experiments.json`） |
| `clauses/` | 富邦 17 個險種（原型 16 個，T146 之後補收）與中國信託 25 個險種的條款 PDF，檔名即 insCode（中信是 `CTBC01`～`CTBC25`，編號對應官網商品清單） | 富邦：`docs/`；中信：組員提供的官網條款 |
| `eval/` | 檢索與問答的驗收題與說明 | `tests/eval/` |
| `seed/` | 資料庫的險種、條文與向量（`catalog.json.gz`，保留 UUID）；不是原型來的，由 `make export-seed` 產生 | 本 repo |

## seed 資料

`make seed` 把 `seed/catalog.json.gz` 讀進資料庫（不需要 Azure、不需要解析 PDF）。向量是 `text-embedding-3-large` 縮成 1024 維；本機的 embedding deployment 名稱不同時，加 `args="--as-model <你的名稱>"`（前提是同一個 model）。資料庫已有 id 不同的險種時會拒絕，請先 `make db-reset`。條款或解析規則改了之後，用 `make ingest` 更新資料庫，再 `make export-seed` 重新產生。

## 條款勘誤

官網 PDF 與實際保單不同的地方，以保單為準，記在 `config/clause_errata.json`，`make ingest` 時套用，**PDF 不改**。比對忽略空白與換行；找不到原文會報錯，PDF 換版後勘誤才不會悄悄失效。原型的對照資料（`tests/golden`）是未套勘誤的官網 PDF，測試比對時另外套上預期的差異。

## 規則

- **費率 JSON 逐格對照保險公司 PDF，不手改。** 有疑慮的格子標為 `null` 並註明，不猜（見 [ADR-0004](../../docs/adr/0004-llm-never-produces-numbers.md)）。要改先回報使用者。
- 國泰沒有條款 PDF，只有費率表（見 [ADR-0006](../../docs/adr/0006-insurance-agent-migration-decisions.md) D4）。
## 方案（選保單）

`config/plans.json` 是沒上傳保單、改選保單那條路的固定測試方案（`fubon_general` → T068、T146）。保險商品與方案由別組負責，**換資料來源只要改 `backend/app/domain/plans.py` 的 `load_plans()`**，回傳同樣的 `Plan`（id、name、險種代碼）；險種代碼要是條款庫存在的 insCode。對話與案件的表只存 insurance_id，路由、前端與表都不用動。測試 `test_plan_codes_exist_in_clause_library` 會擋掉條款庫沒有的代碼。

- `config/plan_products.json` 的費率表對條款是原型的推測，需對照 PDF 核對。
