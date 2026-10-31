# 第 1 階段：報價與推薦核心

目標：旅行規劃進去、推薦結果出來的確定性部分，在新 repo 產生與原型逐筆相同的結果。全部是純函式：不碰資料庫、不呼叫 LLM、不做檢索。

範圍（原型 `src/insurance_agent/`）：

- `pricing/tables.py`、`pricing/quote.py`、`ingest/rates_schema.py`：費率表載入與報價
- `agent/profile.py`：`TripProfile`、`TripProfilePatch`、`merge_patch`、`missing_fields`、`validate_profile`
- `agent/regions.py`、`agent/requirements.py`：目的地對應地區、最低保額門檻、保額階梯
- `agent/recommend.py`：`build_recommendation`（條款警示先用參數注入的假函式，第 2 階段接上）
- `agent/narrate.py` 的確定性部分：`extract_numbers`、`check_numbers`、`render_template`、`render_report`、`DISCLAIMER`

## 步驟

### 1. 產生對照資料

寫一支腳本，在原型裡對固定輸入呼叫上面的函式，把輸出轉成 JSON。案例至少涵蓋：

- `quote()`：天數 1、5、表上沒有的天數；1～4 位旅客；年齡邊界（各費率表欄位的上下限）；租車自駕；含／不含法定傳染病、`infectious=None`；保額達不到需求
- `merge_patch()`：`None` 不覆蓋已知值、無效值被忽略、`no_activities`、`raise_coverage`、自訂保額（萬元）
- `requirements_for()`：日本／歐美、其他地區、查不到的地區（`region_assumed`）、`coverage_steps` 0～3
- `build_recommendation(...).to_dict()`：每組前 3 名、多人租車假設
- `render_template()`、`check_numbers()`：白名單通過與不通過各數例

用 README 規則 1 的方式在原型執行，輸出存成 `backend/tests/golden/pricing.json`、`profile.json`、`recommend.json`、`narrate.json`。腳本本身也放進 `backend/tests/golden/README.md`，之後要重產時照著做。

完成條件：每個列出的案例類別都至少有一筆對照資料。

### 2. 移植測試

把原型 `tests/test_quote.py`、`test_pricing_tables.py`、`test_rates_schema.py`、`test_profile.py`、`test_regions.py`、`test_requirements.py`、`test_recommend.py`、`test_narrate.py`（只取確定性部分）移植到 `backend/tests/domain/`，再加一組讀 `backend/tests/golden/*.json` 逐筆比對的測試。

完成條件：`make test` 跑這些測試，因為還沒有實作而全部紅燈。

### 3. 實作

依模組對照表放到 `backend/app/domain/pricing/` 與 `backend/app/domain/recommend/`。費率表與設定從 `backend/data/` 讀（路徑由 `app.core.config` 提供，測試可以覆寫）。資料結構沿用原型的 dataclass 與 Pydantic model；名詞依 D1 的定案。

完成條件：第 2 步的測試全綠，對照比對零差異。

### 4. 報價 API

新增 `POST /api/v1/quote`（對應原型 `pricing/quote_cli.py` 的參數），回傳可報價方案與不可報價原因。路由函式名不可與既有的重複（`test_operation_ids_are_unique`）。

完成條件：API 測試涵蓋正常報價、表上沒有的天數、旅客超過 4 位的 422；`make client` 後 `make typecheck` 通過。

## 不做

- 條款警示的實際檢索（第 2 階段）
- LLM 改寫摘要（第 3 階段）
- 前端頁面（第 3 階段）
