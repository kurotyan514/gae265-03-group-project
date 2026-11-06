## 比對規則校正（電子 PDF 文字層，應接近 100%）：128/128 (100%)

## 送 OCR 的檔案：63 份，欄位 506 個（答案為可讀的欄位）

### 方案 C：本機 OCR 讀得到的必要欄位
| 分組 | 讀到 |
|---|---|
| 全部 | 461/506 (91%) |
| 類別 C | 151/179 (84%) |
| 語言 ja | 160/176 (91%) |
| 品質 blur_field | 43/44 (98%) |
| 類別 A | 162/172 (94%) |
| 語言 en | 172/188 (91%) |
| 品質 phone_skew | 63/66 (95%) |
| 關鍵欄位（is_critical） | 32/34 (94%) |
| 類別 B | 141/146 (97%) |
| 品質 clean | 175/183 (96%) |
| 語言 zh | 129/142 (91%) |
| 品質 glare_field | 40/45 (89%) |
| 品質 shadow_readable | 65/69 (94%) |
| 品質 shadow_field | 41/44 (93%) |
| 品質 low_resolution_glare | 27/46 (59%) |
| 類別 CONTROL | 7/9 (78%) |
| 品質 cropped_margin | 7/9 (78%) |

### 方案 B：遮蔽結果
- 個資欄位：91 個
- 遮完仍讀得到（漏遮）：5/91 (5%)
- 本機一開始就讀不到（沒辦法確認有沒有遮到，雲端可能讀得到）：0/91 (0%)
- 非個資欄位被誤遮：3/387 (1%)
- 其中關鍵欄位被誤遮：0/32 (0%)

漏遮明細：
  A6-003 ja blur_field policy_ref
  A6-035 zh clean doctor_name
  A6-052 ja shadow_readable card_ref
  A6-057 ja shadow_field card_ref
  A6-065 en clean licence_ref
誤遮明細：
  A6-022 en phone_skew application_ref
  A6-022 en phone_skew application_date
  A6-036 en low_resolution_glare ward

答案為「看不清楚」卻被本機讀出原值：[('A6-006', 'flight_date'), ('A6-027', 'consultation_date'), ('A6-042', 'relationship'), ('A6-048', 'check_in')]

### 速度：OCR 平均 0.54 秒／份（最慢 0.71）；遮蔽後重讀平均 0.52 秒（正式流程不需要重讀）
