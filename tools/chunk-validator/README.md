# 旅遊保險條文 Chunk 品質驗證系統

驗證 Boris 切割的條文 Chunk 是否完整、正確、切對位置、歸屬正確、可追溯，並用繁中 Dashboard 呈現結果、匯出驗收報告。

## 快速開始（Mac）

需要先安裝 [uv](https://docs.astral.sh/uv/)。這是獨立的 uv 專案（不屬於 backend 的 workspace，也不 import `app`），在 `tools/chunk-validator/` 資料夾內：

```bash
uv sync
```

```bash
uv run streamlit run app.py
```

瀏覽器會打開 Dashboard（http://localhost:8501）。**夜間模式**：右上角 ⋮ → 點「Dark」，瀏覽器會記住；側邊欄「PDF 頁面圖片調暗」可降低白底頁面圖片的亮度。（要在這個資料夾內啟動，`.streamlit/config.toml` 的主題設定才會生效。）依序操作：①執行驗證 → 📦導入進度 → ②總覽 → ③問題清單 → ④對照 → ⑤可信度 → ⑥匯出。

不開畫面也可以用命令列：

| 指令 | 用途 |
| --- | --- |
| `uv run python -m validator fetch` | 從 Boris 的 API 抓最新資料，存成快照 |
| `uv run python -m validator import-pdfs` | 從本 repo 的 `backend/data/clauses/`（預設 origin/main）匯入原始 PDF，只讀不改 |
| `uv run python -m validator run` | 用最新快照執行六項驗證 |
| `uv run python -m validator selftest` | 驗證器自我測試（故意埋錯） |
| `uv run pytest` | 自動化測試 |

## 怎麼驗證的（可以直接拿去解釋）

1. **標準答案不是 Boris 的資料。** 用兩套不同的 PDF 工具（pymupdf、pdfplumber）各自讀原始 PDF，只採用「頁面可見範圍內」的文字，再用自己寫的規則切出條文。兩套工具讀法一致的，才當作確定的標準答案。
2. **為什麼只看可見範圍：** 富邦的 PDF 是節錄版，其他章節的文字被放在頁面範圍外，畫面上看不到。如果不過濾，會把看不到的條文誤判成「缺漏」。
3. **狀態的意思：**
   - 🟢 PASS：與兩套工具一致的標準答案相符（只差空白、換行、全半形視為相同）
   - 🔴 FAIL：與兩套工具一致的標準答案不符 → 確定錯誤
   - 🟡 WARNING：兩套工具讀法不同（常見於公式、表格），或屬於可疑但非確定的狀況 → 需要人工看 PDF 頁面圖片
   - ⚪ NOT_VERIFIED：缺資料無法驗證（例如沒有 PDF、API 沒有提供版本欄位）→ **絕不算通過**
4. **驗證器本身也被驗證：**
   - 故意埋錯：在資料副本中做出 16 種錯誤（刪條、改字、切錯邊界、險種錯置、頁碼錯誤…），看驗證器能否抓到
   - 人工標準答案：人看 PDF 頁面圖片標註正確與否，與驗證器判定比對，算出抓對、誤報、漏抓

## 六項驗證與規則代碼

| 項目 | 檢查內容 | 主要規則 |
| --- | --- | --- |
| 1 完整性 | 缺條、多條、重複、空白、沒有向量 | C1 缺漏、C2 重複、C3 非預期條號、C5 無向量、C6 工具意見不一 |
| 2 正確性 | 標題、內文是否忠於 PDF | A1 標題、A2 內文、A3/A4 工具讀法不同 |
| 3 邊界 | 切割位置 | B1 混入他條標題、B2 標題當內文、B3～B7 開頭／結尾錯位 |
| 4 歸屬 | 險種、公司、PDF 對應 | R1 名稱與登記表不符、R2 名稱在 PDF 找不到、R3 章名不符、R4 公司不符 |
| 5 長條文 | 目前規則是「一條一段、不切段」 | L1 超過字數提醒、L2 疑似含附表 |
| 6 可追溯性 | 來源檔、頁碼真的對得上 | T1 來源檔、T2 頁碼超出範圍、T3 文字不在標示頁、T7 PDF 未確認為官方版、T8 API 缺 ID／版本 |

## 資料夾結構

```
tools/chunk-validator/
├─ app.py                 Dashboard（Streamlit）
├─ config/
│  ├─ insurances.csv      險種登記表：險種代碼、公司、名稱、PDF 路徑（新增險種／公司改這裡）
│  ├─ companies.toml      各公司 PDF 版面規則（條文標題格式、頁首制式文字…）
│  └─ settings.toml       API 位址、長條文門檻
├─ validator/
│  ├─ fetch.py            取得資料、存快照（只發 GET）
│  ├─ pdfs.py             PDF 匯入與指紋紀錄
│  ├─ baseline.py         從 PDF 建立標準答案（兩套工具＋可見範圍）
│  ├─ checks/             六項驗證，一項一個檔案
│  ├─ runner.py           執行驗證、存結果
│  ├─ selftest.py         故意埋錯測試
│  ├─ review.py           人工覆核與人工標準答案
│  └─ report.py           匯出 CSV／Excel／HTML
├─ tests/                 自動化測試
└─ data/                  （自動產生，不進 git）snapshots 快照、pdfs 原始 PDF、runs 驗證結果、
                           reviews.json 覆核紀錄、gold.json 人工標準答案
```

## 導入進度（📦 頁）

`config/insurances.csv` 就是「應導入清單」。每個險種會判定一個進度：❓ 未登記 → ⬜ 未導入 → 📄 缺 PDF → 🔴 有錯待修 → 🟡 待人工確認 → 🟢 完成，並寫明下一步由誰做什麼。要新增應導入的險種，就在登記表加一列。

## 新增險種或保險公司

1. 把 PDF 放到 `data/pdfs/<公司名>/<險種代碼>.pdf`
2. 在 `config/insurances.csv` 加一列（代碼要和 Boris 資料中的 `insurance_code` 相同）
3. 重新執行驗證。新公司先套用 `companies.toml` 的 `[default]` 規則；若出現大量 🟡 或誤判，
   先看 PDF 頁面圖片確認原因，再在 `companies.toml` 為該公司加規則，並寫明「依據」（哪份 PDF 哪一頁）
4. 規則改了，把 `validator/config.py` 的 `RULES_VERSION` 升版，並重跑 `uv run pytest` 與自我測試

沒有登記或沒有 PDF 的險種，條文會標示 ⚪ 無法驗證，不會被當成通過。

## 已知限制

- 只能驗證「PDF 裡有文字層」的條款；掃描圖片型 PDF 需要另外加 OCR
- 公式、表格兩套工具常讀法不同，會變成 🟡，需人工看圖
- 驗證規則（條文標題格式）仍是用文字規則判斷；換公司時要先用頁面圖片確認
- 官方 PDF 本身若有錯字，驗證器無法發現（它以 PDF 為準）
