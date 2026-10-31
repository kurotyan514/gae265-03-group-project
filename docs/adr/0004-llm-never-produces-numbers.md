---
status: accepted
---

# LLM 不產生數字：價格與保額由程式算，流程由程式決定

推薦與問答的每個數字（保費、保額、天數）都由確定性的程式產生，LLM 只負責聽懂使用者的話與把結果說成人話。保險的金額一旦錯就是誤導使用者，而 LLM 會在沒有根據時自信地編數字，所以把它擋在數字的產生路徑之外。以下七條來自原型 `insurance_agent`（來源版本 `512c7b1`）的「鐵則」，移植時照搬；路徑是移植後的預定位置，實際以各階段 PR 為準。

## 七條規則

1. **價格與保額由程式算，LLM 絕不產生或改寫數字。** 報價是確定性的純函式，不內插、不四捨五入；費率表上沒有的天數回報「不可報價」。位置：`backend/app/domain/pricing/`。
2. **流程由程式決定，LLM 只負責「聽懂」（抽成 `TripProfilePatch`）和「說人話」（narrate）。** 要問什麼、問幾次、何時結束都寫在 Python 規則裡，行為才可測、可重現。位置：`backend/app/domain/recommend/`、`backend/app/domain/chat/`。
3. **LLM 輸出片段，程式合併。** `None` 不蓋掉已知值，無效值忽略並記錄，LLM 一次抽錯不會洗掉前面問到的資料。位置：`backend/app/domain/recommend/`（`merge_patch`）。
4. **LLM 寫的說明必須通過數字白名單**（`check_numbers`），不通過就退回模板。出處區塊（檔名、頁、欄位）由程式產生，不經過 LLM。位置：`backend/app/domain/recommend/narrate.py`。
5. **條款不明確時保留方案、加警示並附條文**，不自動剔除。替使用者排除方案等於替保險公司解釋條款，由使用者看原文判斷。位置：`backend/app/domain/recommend/`（條款警示）。
6. **費率表走 JSON + 程式，條款走 RAG；費率表不進向量庫。** 價格是「完全一致」的資料，向量檢索只會給出相似的數字。位置：`backend/data/rates/`、`backend/app/domain/pricing/`。
7. **資料有疑慮時不猜。** 例如富邦公版 `g3_300` 第 5 天原表印成「1,17」，標為 `None` 並註明請向保險公司確認。費率 JSON 逐格對照 PDF，不手改。位置：`backend/data/rates/`。

## Consequences

- 每一條都要有對照測試（`backend/tests/golden/`）；不一致時查原因並回報，不改對照資料配合新程式。
- 想讓 LLM 「順便」算價格或比較保額的功能，都要先改這份 ADR。
