# 第 4 階段：方案問答

目標：使用者針對推薦的方案或任何險種提問（保險範圍、除外責任、理賠文件），系統回條文原文與出處，白話摘要受數字白名單約束，找不到就明說。

依據：原型 `agent/qa.py`、`agent/qa_eval.py`、`design/2026-10-28-next-features-spec.md` 第 ② 節、`design/plans/2026-10-29-qa-eval-results.md`。

## 規則（照原型）

- 原文與出處永遠給；摘要沒通過數字白名單（問題與命中條文裡出現的數字）就只給原文
- 第一筆相似度低於 `MIN_SIMILARITY=0.55` → `not_found`，不列出不相關條文
- 第一筆沒有同時被向量與關鍵字檢索命中 → 信心不足，只給原文並附「條款沒有明確規定…請向保險公司確認」
- 摘要截掉沒寫完的最後一句；結尾附免責聲明
- 有推薦時預設鎖定該方案的險種（第 2 階段條款警示用的對應）；使用者可以改問其他險種

## 步驟

### 1. 移植與實作

移植 `tests/test_qa.py`（fake summarizer），實作放 `backend/app/domain/qa/`，檢索用第 2 階段的混合檢索。原型「各公司各查再交錯合併」改成「各險種各查再交錯合併」。

完成條件：`test_qa.py` 的案例全部通過，包含 `found`、信心不足、`not_found`、白名單擋下。

### 2. `/api/v1/ask`

輸入 `question`、可選的 `session_id`（從對話取推薦的方案）與險種代碼；輸出 `status`、`summary`、`hits[]`（險種、條號、頁碼、原文）、`blocked_numbers`、`disclaimer`。沿用第 3 階段的限流與存取碼。

完成條件：API 測試涵蓋三種 status 與鎖定方案；`make client`、`make typecheck` 通過。

### 3. 14 題驗收

移植 `qa_eval.py` 為 `backend/app/eval/qa.py`，Makefile 加 `make eval-qa`（在 backend 容器內執行），報告寫 `docs/reports/qa-<日期>-<供應商>.md`。

`qa_questions.json` 的期望答案改寫成險種與條號，規則同第 2 階段第 5 步：對應不出來的標記「條文庫未收錄」、不編造期望答案。

完成條件：報告列出每題結果與總分，和原型的 7/14 並列比較並說明差異來源（條文庫不同、模型不同）；照實記錄，不調規則。

### 4. 前端

推薦卡片加「問這個方案」，另有獨立的問答頁可以選險種。顯示原文、出處、摘要與免責聲明；`not_found` 與信心不足要有明顯的提示。MSW 加假資料。

完成條件：`VITE_MOCK=true` 下三種 status 的畫面都看得到；e2e 測一題 `not_found`。

## 不做

- 保單上傳與分析（原型也只有規格）
