# 理賠文件上傳的預覽與誠實進度（規格 #287、ADR-0027）

2026-11-11 完成並由設計者確認。決策與理由見 [ADR-0027](../../adr/0027-claim-document-upload-honest-progress.md)；名詞見 [GLOSSARY](../../../GLOSSARY.md) 的**小助理**、**處理清單**、**處理階段**。

## 已完成

| 票 | PR | 內容 |
| --- | --- | --- |
| #288 | #297 | 拆出單份處理列與結果分類（行為不變） |
| #289 | #298 | 上傳路由記耗時日誌 `document_recognize_ms` |
| #293 | #302 | 誠實的處理過程：不確定進度、超過 8 秒安撫、處理完才顯示結果；上傳回應多 `stored` |
| #292 | #310 | 預覽：圖片縮圖與放大、PDF／HEIC 圖示 |
| #301 | #309 | 辨識器沒有「重新檢查」時，確認文件的回應改成已確認 |
| #294 | #311 | 網路中斷：背景重新讀取確認；太大與不支援的檔案送出前就擋下；不設前端逾時 |
| #304 | #308 | 通知念摘要、待辦讀最新、清理與 e2e 探針 |
| #305 | #312 | 有提醒的合格結果不折疊，提醒數寫在各類別括號裡 |
| #291 | #316 | 依設計者回覆：不顯示處理階段、連線中斷只寫「連線中斷，上傳失敗」 |

畫面規則（設計者確認；11/13 改：處理中逐步亮起「讀取內容 → 對應待辦 → 檢查規則」，最短 2 秒、只演一次，失敗原因不寫停在哪一步、不重複「沒有存到 Google Drive」，見 ADR-0027「2026-11-13 設計者修訂」）：處理中原本只有「小助理正在處理這份文件…」，排在後面的標「等待中」；處理完先顯示摘要，**預設只列沒通過的文件**；合格且沒有提醒的折疊在「看全部明細」；只有不合格（不合格、無法辨識、辨識失敗、沒有完成、上傳失敗）有紅字，「需要你確認」與「有提醒」是琥珀色且不折疊；不顯示處理階段。

## 回歸（2026-11-11，main `cdfea66`）

- `incident-`、`dev-incident`、`google-dev-incident`、`home`、`dev-ui` 共 246 個 e2e 通過（CI 不跑 e2e，本機跑）。
- 第一次完整跑時 `dev-incident` 的「事件流程測試台」失敗 1 次（15 秒逾時）；之後單獨跑 3 次、整組再跑 2 次都通過。這個 spec 在完整並行時偶發失敗，原因沒有查出來。
- 390px 與桌機的真實畫面截圖已由設計者逐項確認（#291 第二輪）。

## 耗時日誌：怎麼收集

每次 `POST /incidents/{id}/documents` 記一行（不含檔名、檔案內容與使用者資料）：

```text
document_recognize_ms=1200 status=recognized content_type=application/pdf size_bucket=<1MB
```

`document_recognize_ms` 量的是 6 號辨識器的等待時間（不含資料庫寫入）；`size_bucket` 只有 `<1MB`、`1-5MB`、`5-10MB`。取得方式：

```bash
# 開發環境（repo 根目錄）
docker compose logs --no-log-prefix backend | grep document_recognize_ms

# 正式環境（在 VM 上，repo 根目錄）
docker compose -f compose.prod.yaml logs --no-log-prefix backend | grep document_recognize_ms
```

算份數、p95 與超過 5 秒的比例（把上面的輸出接在後面）：

```bash
... | python3 -c "import sys,re,math; v=sorted(int(m) for m in re.findall(r'document_recognize_ms=(\d+)',sys.stdin.read())); n=len(v); print('份數',n,'p95(ms)',v[math.ceil(0.95*n)-1] if n else None,'超過5秒比例',round(sum(x>5000 for x in v)/n,2) if n else None)"
```

`status=error` 的幾行是辨識器丟出例外的情況，也會算進去；要排除就先用 `grep -v status=error`。

## 何時重新評估真的串流

收集至少 30 份**真實**上傳（真 Azure、真 Google Drive）後，若 **p95 超過 8 秒，或有超過兩成的請求超過 5 秒**，就另開票評估真的串流；屆時要動 6 號契約（升版並寫進 [contract-changelog.md](contract-changelog.md)），並取代 ADR-0027。**由 6 號負責人在真實環境收集**（開發環境用假辨識器，數字沒有意義）；還沒有人收集過。

## 已知限制

- **#196（確認成 D10 時把檔案搬到行程資料夾）沒有在真實 Google Drive 驗證過**：`drive.file` 權限能不能搬 App 自己建立的檔案，是依 Google 文件推論的。驗證方式：上傳一份看不出種類的檔案 → 在待辦選「填寫理賠申請書」確認 → 到 Drive 看檔案位置。搬不動只會沿用原位置，不影響確認。
- **連線中斷後的重新讀取窗口約 9 秒**（4 次、間隔 3 秒）。真實的 6 號處理（辨識加存 Drive）可能更久，窗口內沒讀到就顯示「連線中斷，上傳失敗」，旅客重傳可能產生重複檔案。用戶端斷線後伺服器會不會繼續處理，沒有驗證。
- **「追加到已完成的待辦」同時帶「已收到，還缺…」說明時，會被當成提醒顯示**（`reminderOf`，`uploadRecognition.ts`）：真實 6 號會不會產生這個組合沒有驗證，所以沒修。
- 提醒只顯示在這一次上傳的處理清單，重新整理後沒有；規格書 v3.8 的待辦「有提醒」標籤、「檔案刪除或改傳後提醒消失」、送件時不列提醒還沒做（`recognition_reason` 有存在資料庫，技術上可行）。
- `/dev/ui` 的處理清單靜態原型（#290）是原型頁，沒有跟著拿掉處理階段那一行。

## Out of Scope（仍成立）

- 真的串流階段事件（SSE 或輪詢）、多份同時處理、重新整理後從 Drive 讀回縮圖、2-1 保單上傳的動畫（#283 另議）。
