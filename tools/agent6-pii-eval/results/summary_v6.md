## 比對規則校正（電子 PDF 文字層，應接近 100%）：128/128 (100%)

## 送 OCR 的檔案：63 份，欄位 506 個（答案為可讀的欄位）

### 方案 C：本機 OCR 讀得到的必要欄位
| 分組 | 讀到 |
|---|---|
| 全部 | 491/506 (97%) |
| 類別 C | 166/179 (93%) |
| 語言 ja | 172/176 (98%) |
| 品質 blur_field | 44/44 (100%) |
| 類別 A | 171/172 (99%) |
| 語言 en | 182/188 (97%) |
| 品質 phone_skew | 65/66 (98%) |
| 關鍵欄位（is_critical） | 32/34 (94%) |
| 類別 B | 145/146 (99%) |
| 品質 clean | 182/183 (99%) |
| 語言 zh | 137/142 (96%) |
| 品質 glare_field | 45/45 (100%) |
| 品質 shadow_readable | 69/69 (100%) |
| 品質 shadow_field | 44/44 (100%) |
| 品質 low_resolution_glare | 33/46 (72%) |
| 類別 CONTROL | 9/9 (100%) |
| 品質 cropped_margin | 9/9 (100%) |

### 方案 B：遮蔽結果
- 個資欄位：91 個
- 遮完仍讀得到（漏遮）：1/91 (1%)
- 本機一開始就讀不到（沒辦法確認有沒有遮到，雲端可能讀得到）：0/91 (0%)
- 非個資欄位被誤遮：6/407 (1%)
- 其中關鍵欄位被誤遮：0/32 (0%)

漏遮明細：
  A6-065 en clean licence_ref
誤遮明細：
  A6-022 en phone_skew application_ref
  A6-022 en phone_skew application_date
  A6-036 en low_resolution_glare ward
  A6-070 ja shadow_readable issue_date
  A6-072 en low_resolution_glare property_description
  A6-072 en low_resolution_glare issue_date

答案為「看不清楚」卻被本機讀出原值：[('A6-006', 'flight_date'), ('A6-027', 'consultation_date'), ('A6-042', 'relationship'), ('A6-048', 'check_in')]

### 速度：OCR 平均 0.62 秒／份（最慢 0.82）；遮蔽後重讀平均 0.60 秒（正式流程不需要重讀）
