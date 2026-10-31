---
status: accepted
---

# 向量固定 1024 維；條文一條一段，BM25 + 向量混合檢索

條文向量統一為 1024 維，新增設定 `EMBEDDING_DIMENSIONS=1024`：Ollama 用 `bge-m3`，Azure OpenAI 用 `text-embedding-3-large` 並指定 `dimensions=1024`，fake embedding 跟著設定走。檢索單位是一條條文一段，不依字數切。原型在 32 題考卷上比較過 embedding 模型與切塊方式（`design/research/2026-10-28-rag-chunk-embedding-comparison.md`，來源版本 `512c7b1`），結論如下。

## 實驗結論

- **embedding 模型影響最大。** 前 5 名命中數：bge-m3 25/32、text-embedding-3-large 23/32、embeddinggemma 20/32、nomic-embed-text 12/32。
- **nomic-embed-text 不適合中文條款**：只用向量時 32 題只中 2 題，放進混合檢索後比只用 BM25 還差。不使用。
- **bge-m3 最好**，只用向量就有 25/32，加上 BM25 沒有再進步，但混合檢索仍保留（BM25 補專有名詞）。
- **一條條文一段**比依字數切好。
- 查詢改寫、重新排序目前不划算，不移植。
- 限制：只有 32 題，差 1～2 題不具意義；只測了國泰、富邦兩家。

## Considered Options

- **沿用 1536 維（fake／Azure 預設）**：Ollama 的 bge-m3 放不下，且不同模型的向量不能混比。
- **每個供應商各自的維度**：欄位要跟著換，migration 變複雜。
- **統一 1024 維**（採用）：`text-embedding-3-large` 支援縮維；代價是 Azure 縮維後的品質要自己評估。

## Consequences

- 資料表欄位為 `vector(1024)`，並記錄 `model`；換模型必須重建向量。
- 兩種供應商的檢索評估分開跑、分開記錄，結果註明供應商。
- 開發用 Ollama 與正式用 Azure 的檢索品質不同，不可互相代表。
