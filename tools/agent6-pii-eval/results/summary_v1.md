## 比對規則校正（電子 PDF 文字層，應接近 100%）：128/128 (100%)

## 送 OCR 的檔案：63 份，欄位 506 個（答案為可讀的欄位）

### 方案 C：本機 OCR 讀得到的必要欄位
| 分組 | 讀到 |
|---|---|
| 全部 | 451/506 (89%) |
| 類別 C | 148/179 (83%) |
| 語言 ja | 154/176 (88%) |
| 品質 blur_field | 40/44 (91%) |
| 類別 A | 159/172 (92%) |
| 語言 en | 170/188 (90%) |
| 品質 phone_skew | 62/66 (94%) |
| 關鍵欄位（is_critical） | 31/34 (91%) |
| 類別 B | 137/146 (94%) |
| 品質 clean | 170/183 (93%) |
| 語言 zh | 127/142 (89%) |
| 品質 glare_field | 40/45 (89%) |
| 品質 shadow_readable | 64/69 (93%) |
| 品質 shadow_field | 41/44 (93%) |
| 品質 low_resolution_glare | 27/46 (59%) |
| 類別 CONTROL | 7/9 (78%) |
| 品質 cropped_margin | 7/9 (78%) |

### 方案 B：遮蔽結果
- 個資欄位：91 個
- 遮完仍讀得到（漏遮）：18/91 (20%)
- 本機一開始就讀不到（沒辦法確認有沒有遮到，雲端可能讀得到）：0/91 (0%)
- 非個資欄位被誤遮：3/379 (1%)
- 其中關鍵欄位被誤遮：0/31 (0%)

漏遮明細：
  A6-003 ja blur_field policy_ref
  A6-007 ja shadow_readable person_name
  A6-008 zh clean person_name
  A6-009 en shadow_field person_name
  A6-010 zh clean person_name
  A6-011 en clean person_name
  A6-012 ja low_resolution_glare person_name
  A6-024 zh low_resolution_glare person_name
  A6-034 ja shadow_readable doctor_name
  A6-035 zh clean doctor_name
  A6-036 en low_resolution_glare doctor_name
  A6-040 en phone_skew related_person
  A6-041 ja clean related_person
  A6-048 ja low_resolution_glare person_name
  A6-052 ja shadow_readable card_ref
  A6-056 en clean card_ref
  A6-057 ja shadow_field card_ref
  A6-060 zh low_resolution_glare person_name
誤遮明細：
  A6-036 en low_resolution_glare admission_date
  A6-036 en low_resolution_glare issue_date
  A6-066 ja glare_field valid_territory

答案為「看不清楚」卻被本機讀出原值：[('A6-006', 'flight_date'), ('A6-027', 'consultation_date'), ('A6-042', 'relationship'), ('A6-048', 'check_in')]

### 速度：OCR 平均 0.55 秒／份（最慢 0.74）；遮蔽後重讀平均 0.53 秒（正式流程不需要重讀）
