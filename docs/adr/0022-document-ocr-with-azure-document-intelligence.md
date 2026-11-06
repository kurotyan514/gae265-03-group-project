---
status: proposed
---

# 理賠文件的照片與掃描檔用 Azure Document Intelligence 讀文字

文件辨識要先讀出文件上的文字。電子 PDF 有文字層，程式自己讀；照片（JPG、PNG）、掃描檔與沒有文字層的 PDF，送 Azure Document Intelligence 讀。這是 [ADR-0012](0012-text-extractor-and-ocr-module.md) 留下的「OCR 供應商未定」在理賠文件上的選擇，實作掛在 `TextExtractor` 介面之後。

- **電子 PDF 自讀**：有文字層就用現有的抽文字程式，不送外部服務。
- **原圖送出是例外**：[ADR-0009](0009-policy-document-personal-data.md) 要求個資先在程式內去識別化才送雲端，但圖片上的個資無法先遮。全組同意，照片與掃描檔以原圖送 Azure，這是 ADR-0009 的例外，僅限文件辨識使用。上傳頁要告知使用者「文件會送到 Azure 辨識」。
- **讀出之後照常去識別化**：Azure 回傳的文字送進 LLM 或 log 之前，照 ADR-0009 去識別化；6 號自己的出口（LLM、log）另外處理被換行拆開的姓名與檔名。
- **read 與 layout 都接、可切換**：兩種模型都實作，用設定切換；評估（第 4 步）量完準確度與成本後再定預設值。
- **逐欄信心度**：每個需要的欄位都看 Azure 回的信心度，門檻暫定 0.8。低於門檻、模糊、裁切、欄位沒讀到 → 不通過（請使用者重拍）；欄位是手寫 → 不確定。
- **數字不由 LLM 產生**：日期、時間、航班等欄位一律取自讀出的文字，LLM 只當分類的後援，結果一律回「不確定」（[ADR-0004](0004-llm-never-produces-numbers.md)）。

## Considered Options

- **本機 Tesseract**：不出境，但手機斜拍、反光的中文文件準確度不夠，資料集的 C 類樣本幾乎都會失敗。沒採用。
- **具視覺能力的 LLM 直接看圖**：一樣要送原圖出去，還可能自己「補」出看不清的數字，違反 ADR-0004。沒採用。
- **先用 Azure Language 遮個資再辨識**：查證後發現它的文件型個資遮蔽要先把原檔上傳到 Blob，而且不支援 JPG、PNG，無法取代告知。暫不採用；若第 4 步驗收發現個資外洩不是 0 次，再評估文字版的個資偵測。

## Consequences

- 要新增 Azure Document Intelligence 的端點、金鑰與模型設定（`config.py`、`.env.example`、`.env.prod.example` 同步），Azure 資源另外申請，不在這份決定範圍。
- 單份照片的辨識時間會比電子 PDF 長，上傳頁要有處理中的狀態。
- 實作並驗收後把狀態改為 accepted，並補上 read／layout 的預設值與實測準確度。
