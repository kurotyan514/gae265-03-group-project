# backend/data

Dockerfile 只複製 `backend/`，資料放這裡才會進 image。`rates/`、`eval/` 與部分 `config/` 是從原型 `insurance_agent`（來源版本 `512c7b1`）複製進來的，檔案與原型的 sha256 完全相同；`clauses/` 與 `seed/` 是本 repo 的資料。

| 資料夾 | 內容 | 原型來源 |
| --- | --- | --- |
| `rates/` | 費率表 JSON（富邦 6 份、國泰 2 份） | `data/rates/` |
| `config/` | 地區、門檻、合訂本拆分清單（`clause_bundles.json`）、九個方案（`plans.json`）、條款勘誤、查詢同義詞 | `config/`（不含 `rag_experiments.json`、`fubon_insurances.json`、`plan_products.json`；後兩者與險種清單已由新的拆分清單與方案取代） |
| `clauses/` | 富邦、安達、泰安、臺產、華南五份官網條款合訂本（`fubon.pdf`、`chubb.pdf`、`taian.pdf`、`taiwan_fire.pdf`、`huanan.pdf`），依 `config/clause_bundles.json` 拆成 39 個險種（[ADR-0014](../../docs/adr/0014-clause-bundles-and-nine-plans.md)） | 組員提供的官網條款（`seed/` 資料夾的九份 PDF，其中三組基礎型與進階型內容相同，安達基礎型是進階型的子集，各只放一份） |
| `eval/` | 檢索與問答的驗收題與說明 | `tests/eval/` |
| `source/` | 組員整理的易安網試算表「日本旅遊保險_保費保障矩陣.xlsx」（保費矩陣、保障重點、完整保障明細） | 本 repo |
| `seed/` | 資料庫的險種、條文與向量（`catalog.json.gz`，保留 UUID，由 `make export-seed` 產生）；方案保費與保障明細（`plan_data.json`，由 `make plan-data` 從 `source/` 的試算表產生） | 本 repo |

## seed 資料

`make seed` 把 `seed/catalog.json.gz` 讀進資料庫（不需要 Azure、不需要解析 PDF）。向量是 `text-embedding-3-large` 縮成 1024 維；本機的 embedding deployment 名稱不同時，加 `args="--as-model <你的名稱>"`（前提是同一個 model）。資料庫已有 id 不同的險種時會拒絕，請先 `make db-reset`。條款或解析規則改了之後，用 `make ingest` 更新資料庫，再 `make export-seed` 重新產生。

## 方案保費與保障（spec #48）

`seed/plan_data.json` 是九個方案的保費（`plan_premium`）與完整保障明細（`plan_benefit`），來源是 `source/日本旅遊保險_保費保障矩陣.xlsx`：易安網實際試算，日本、1 位旅客、4–10 天（完整 24 小時計日）、身故保額 200–1,000 萬。金額存整數元；試算表沒有的保額、天數或「未提供」就是沒有報價，不推估（[ADR-0004](../../docs/adr/0004-llm-never-produces-numbers.md)）。保障項目的類別由「保障重點」推出，轉換時會核對兩表金額。`make seed` 每次清空兩張表再整批寫入。

試算表換版：換掉 `source/` 的 xlsx → `make plan-data`（方案名稱對不到 `config/plans.json`、兩表金額不一致都會報錯）→ 看 `plan_data.json` 的 diff 並 commit → `make seed`。

## 條款勘誤

官網 PDF 與實際保單不同的地方，以保單為準，記在 `config/clause_errata.json`，`make ingest` 時套用，**PDF 不改**。比對忽略空白與換行；找不到原文會報錯，PDF 換版後勘誤才不會悄悄失效。目前沒有勘誤。

## 規則

- **費率 JSON 逐格對照保險公司 PDF，不手改。** 有疑慮的格子標為 `null` 並註明，不猜（見 [ADR-0004](../../docs/adr/0004-llm-never-produces-numbers.md)）。要改先回報使用者。
- 國泰沒有條款 PDF，只有費率表（見 [ADR-0006](../../docs/adr/0006-insurance-agent-migration-decisions.md) D4）。
## 方案（選保單）

`config/plans.json` 是九個方案：每個方案的名稱、公司與它含的險種（`insurances`，有 `chapters` 的只含這幾章加共同條款）。保險商品與方案由別組負責，**換資料來源只要改 `backend/app/domain/plans.py` 的 `load_plans()`**，回傳同樣的 `Plan`；險種代碼要是條款庫存在的 insCode。對話與案件的表只存 insurance_id，路由、前端與表都不用動。測試會擋掉條款庫沒有的代碼或章名，也會擋掉沒有任何方案使用的險種。

## 更新條款

換了 PDF 或改了 `config/clause_bundles.json` 之後：`make test`（拆分測試會指出錨點對不上或條號不連續的地方）→ 清掉險種相關的表（`TRUNCATE insurance CASCADE`，條文與向量會一起刪）→ `make ingest` → `make export-seed`。
