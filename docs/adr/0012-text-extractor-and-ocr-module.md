---
status: proposed
---

# 抽文字做成 `TextExtractor` 介面，OCR 另做獨立模組（建議，尚未實作）

保單解析與日後流程圖的 6（文件辨識）都需要從 PDF 或圖片取得文字。目前只支援有文字層的 PDF（掃描檔依 [ADR-0007](0007-ingest-agent-sse-progress.md) 會被拒絕）。建議把「抽文字」抽成一個介面，現在只有文字型 PDF 的實作，OCR 之後以獨立模組掛進來，兩邊共用。

- 介面：輸入檔案內容，輸出每頁文字與頁碼（`list[PageText]`）。呼叫端（保單解析、日後的文件辨識）只依賴這個介面。
- 文字型 PDF 的實作沿用現有的 `app.ingest.clauses.extract_pages` 一類的邏輯。
- 沒有文字層的檔案回明確錯誤，不靜默回空字串。
- OCR 實作的供應商未定：候選有雲端文件辨識服務、本機的 Tesseract、具視覺能力的 LLM，實作時依成本、中文準確度、個資是否出境再決定。
- OCR 的輸出一樣要先走 [ADR-0009](0009-policy-document-personal-data.md) 的去識別化，才能進 LLM。

## Consequences

- 這份只是建議：v1 不寫 OCR 程式。
- OCR 上線後單一工作會跑到數分鐘，依 [ADR-0003](0003-no-background-worker-yet.md) 的條件重新評估 Celery，並把保單處理進度改成更適合長工作的方式。
- 實作 OCR 時把狀態改為 accepted，並補上供應商的選擇與理由。
