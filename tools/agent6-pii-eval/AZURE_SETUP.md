# 申請 Azure Document Intelligence 試用金鑰，並跑方案 A／B 實測

目的：用同一批合成文件，比較「原圖送 Azure」（方案 A）、「遮過再送 Azure」（方案 B）和本機 OCR 的準確度。這是決定要不要改規格書的關鍵數字。

## 0. 先問組員（最快）

專案已經在用 Azure OpenAI（`.env.example` 裡有 `AZURE_OPENAI_*`），代表團隊已經有 Azure 訂閱。**請管理這個訂閱的人（Sean 或 Jerry）在同一個訂閱裡開 Document Intelligence**，不必另外申請帳號。

順便請組員確認：測試集的 README 寫明「是否執行真實 OCR 由團隊另行決定」。這批是全部虛構的合成資料，送 Azure 的風險很低，但仍然要讓組員知道。

## 1. 建立資源（在 Azure Portal，約 5 分鐘）

1. 打開 https://portal.azure.com ，點「建立資源」，搜尋 **Document Intelligence**（舊名 Form Recognizer），然後點「建立」。
2. 依序填：
   - **訂閱**：團隊現有的訂閱。
   - **資源群組**：用現有的或新建，例如 `gae265-agent6`。
   - **區域**：選 **Japan East** 或 **East Asia**。理賠文件會在這個區域處理，之後寫告知文字時也要寫明。
   - **名稱**：例如 `gae265-agent6-di`。
   - **定價層**：**Free F0**，每月 500 頁免費。注意每個訂閱只能有一個 F0；如果已經被用掉，就選 S0（read 模型每 1000 頁約 1.5 美元，這次實測大約 130 頁）。
3. 點「檢閱 + 建立」，再點「建立」，等部署完成後點「前往資源」。
4. 左邊選單點「金鑰與端點」，複製 **KEY 1** 和 **端點**。

> 金鑰不要貼到聊天、Issue 或專案檔案裡。

## 2. 把金鑰存在 Mac 上（專案外面，不會被 commit）

在 Mac 的終端機依序執行：

```bash
mkdir -p ~/.config/agent6 && chmod 700 ~/.config/agent6
```

```bash
touch ~/.config/agent6/azure.env && chmod 600 ~/.config/agent6/azure.env && open -e ~/.config/agent6/azure.env
```

在打開的文字編輯器裡貼上這兩行，換成你複製的值，然後存檔：

```
AZURE_DI_ENDPOINT=https://<你的資源名稱>.cognitiveservices.azure.com/
AZURE_DI_KEY=<KEY 1>
```

## 3. 跑實測

可以在手機上跟 Claude 說「跑 Azure 實測」，或在 Mac 的終端機自己執行：

```bash
.venv-ocr/bin/python -I tools/agent6-pii-eval/azure_eval.py <資料集>/agent6_dataset_v1 tools/agent6-pii-eval/out_v6
```

（`.venv-ocr` 和遮過的圖要先照 REPORT.md「怎麼重跑」的步驟建好。）

- 每份文件要送兩次：一次原圖、一次遮過的圖，總共約 130 次請求。為了配合免費層的速率限制，每次間隔 3.5 秒，全部大約 10 分鐘。
- 中斷了直接重跑就好，已經完成的會跳過。
- 結果寫在 `tools/agent6-pii-eval/out_v6/azure_results.jsonl`，最後會印出與本機的對照表。

## 4. 實測完

- 不再需要的話，到 Portal 刪除資源群組，金鑰就會一起失效。
- 正式接進 6 號時，設定名稱要照專案規則，同步加進 `backend/app/core/config.py`、`.env.example`、`.env.prod.example`（ADR-0022 的 Consequences）。這份實測用的 `~/.config/agent6/azure.env` 只是暫時的做法。
