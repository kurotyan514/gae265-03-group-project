# gae265_03_group_project

根據旅行規劃推薦旅遊保險、並依條款回答問題的 SPA。

## 部署到 Azure

正式環境是一台 Azure B2s VM，用 `compose.prod.yaml` 跑 Postgres、backend 與 Caddy（自動 HTTPS），架構與取捨見 [docs/adr/0001](docs/adr/0001-single-vm-docker-compose-deploy.md)。以下指令用 [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)，先 `az login`；用 Azure Portal 操作也可以，設定值相同。

### 1. 建立 Azure OpenAI deployment

正式環境的 LLM 與 embedding 一律走 Azure OpenAI（VM 跑不動本機模型）。在 Azure OpenAI 資源中各建立一個 chat model 與 embedding model 的 deployment，記下：

- Endpoint（`https://<資源名稱>.openai.azure.com/`）與 API key
- Chat deployment 名稱、embedding deployment 名稱

### 2. 建立 VM

```bash
RG=gae265-rg
LOCATION=japaneast          # 區域，也是網址的 <區域>
DNS_NAME=gae265-demo        # 網址的 <名稱>，該區域內不能重複

az group create -n $RG -l $LOCATION
az vm create -g $RG -n gae265-vm \
  --image Ubuntu2404 --size Standard_B2s \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard --public-ip-address-dns-name $DNS_NAME
az vm open-port -g $RG -n gae265-vm --port 80,443 --priority 900
```

- `--public-ip-address-dns-name` 就是 DNS 名稱標籤，網址是 `$DNS_NAME.$LOCATION.cloudapp.azure.com`（已建好的 VM 到 Portal 的公用 IP →「設定」→「DNS 名稱標籤」設定）。
- 80 要開：Let's Encrypt 用它驗證網域；22（SSH）`az vm create` 預設已開。
- 不 demo 時 `az vm deallocate -g $RG -n gae265-vm` 停機省錢，要用時 `az vm start`；網址不變。

### 3. VM 初次設定

```bash
ssh azureuser@$DNS_NAME.$LOCATION.cloudapp.azure.com

# 安裝 docker（含 compose plugin），讓目前使用者免 sudo
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit   # 重新登入讓群組生效
```

重新 SSH 進去後：

```bash
git clone https://github.com/kurotyan514/gae265-03-group-project.git
cd gae265-03-group-project
cp .env.prod.example .env
nano .env
```

`.env` 依 `.env.prod.example` 的註解填寫，只存在 VM 上、不進 git：

- `DOMAIN=<名稱>.<區域>.cloudapp.azure.com`
- `POSTGRES_PASSWORD`：強密碼（必填）
- `LLM_PROVIDER=azure_openai`，`AZURE_OPENAI_ENDPOINT`、`AZURE_OPENAI_API_KEY`、`AZURE_OPENAI_CHAT_DEPLOYMENT`、`AZURE_OPENAI_EMBEDDING_DEPLOYMENT` 填步驟 1 的值（缺任一項 backend 啟動即失敗）

repo 若是 private，clone 前先在 VM 上 `ssh-keygen` 並把公鑰加到 GitHub repo 的 Deploy keys（唯讀），改用 SSH 網址 clone。

### 4. 首次啟動

在 VM 的 repo 根目錄：

```bash
docker compose -f compose.prod.yaml up -d --build
docker compose -f compose.prod.yaml ps    # db、backend、caddy 都是 running／healthy
```

backend 啟動時會自動套用 migration。Caddy 第一次啟動會申請憑證，log 可用 `docker compose -f compose.prod.yaml logs -f caddy` 看。

### 5. 之後的部署

把要上線的變更 merge 到 `main` 後，在本機 repo 根目錄執行：

```bash
make deploy DEPLOY_HOST=azureuser@<名稱>.<區域>.cloudapp.azure.com
```

它會 SSH 到 VM，在 `~/gae265-03-group-project`（VM 上 repo 位置不同時加 `DEPLOY_DIR=<路徑>`）執行 `git pull` 與 `docker compose -f compose.prod.yaml up -d --build`。`DEPLOY_HOST`／`DEPLOY_DIR` 從命令列或環境變數傳入（例如在 shell 設定檔 `export DEPLOY_HOST=...`），不寫在 `.env`。

### 6. 驗收

用瀏覽器開 `https://<名稱>.<區域>.cloudapp.azure.com`：網址列顯示憑證有效，首頁顯示健康狀態。

注意：不要 `docker compose -f compose.prod.yaml down -v`，會刪掉資料庫與憑證（重新申請受 Let's Encrypt 頻率限制）。
