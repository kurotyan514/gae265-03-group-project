#!/usr/bin/env bash
# 首次架設正式環境 VM 的精靈：每一步先顯示指令，確認後才執行。細節見 docs/deploy.md
#
# 流程：
#   1. 用 az 建 VM、開 port（Azure 端）
#   2. 產生部署金鑰，取得三個 GitHub secret 的值
#   3. 在 VM 上裝 Docker、clone repo、填 .env
#   4. 第一次部署、GHCR 改 public、匯入 seed（GitHub／VM 端）
#
# 可用環境變數覆蓋預設值，例如：RG=GAE26503RG ./scripts/setup-vm.sh
set -euo pipefail

RG=${RG:-gae265-03-group-project}        # Azure 資源群組名稱
VM=${VM:-gae265-03}                      # VM 名稱，同時是網域前綴（<VM>.<區域>.cloudapp.azure.com）
ADMIN=${ADMIN:-azureuser}                # VM 上的登入帳號
LOCATION=${LOCATION:-eastasia}           # 區域；資源群組已存在時會改用群組的區域
KEY=${KEY:-$HOME/.ssh/gae265_deploy}     # 部署專用 SSH 金鑰（私鑰路徑，公鑰是 .pub）

# 顯示指令、等你輸入 y 才執行；其他輸入就略過這一步
run() {
  printf '\n$ %s\n' "$*"
  read -r -p '執行？[y/N] ' a
  if [[ $a == y ]]; then "$@"; else echo '（略過）'; fi
}
# 印出需要你手動操作的說明，做完按 Enter 繼續
pause() { printf '\n%s\n' "$1"; read -r -p '完成後按 Enter…' _; }

# 需要 Azure CLI；還沒登入就先登入
command -v az >/dev/null || { echo '請先安裝 Azure CLI'; exit 1; }
az account show >/dev/null 2>&1 || run az login

# 資源群組已存在（例如課程訂閱沒有建立權限）就直接用它，區域跟著群組
if [[ $(az group exists -n "$RG") == true ]]; then
  LOCATION=$(az group show -n "$RG" --query location -o tsv)  # 讀出群組所在區域
  RG_EXISTS=1
fi

create_vm() {
  # 群組不存在才建立（az group create 需要訂閱層級的寫入權限）
  [[ -n ${RG_EXISTS:-} ]] || az group create -n "$RG" -l "$1" >/dev/null || return
  # 建 VM：Ubuntu 24.04、Standard_B2s（2 vCPU／4 GB）、
  #   --generate-ssh-keys：沒有 ~/.ssh/id_rsa 就產生一把，並放到 VM 上
  #   --public-ip-address-dns-name：公開 IP 的 DNS 名稱，組成 <VM>.<區域>.cloudapp.azure.com
  #   az vm create 會自動開 22（規則 default-allow-ssh）
  az vm create -g "$RG" -n "$VM" -l "$1" --image Ubuntu2404 --size Standard_B2s \
    --admin-username "$ADMIN" --generate-ssh-keys \
    --public-ip-address-dns-name "$VM" --public-ip-sku Standard
}
printf '\n$ az group create + az vm create（%s，Standard_B2s，Ubuntu 2404）\n' "$LOCATION"
read -r -p '執行？[y/N] ' a
if [[ $a == y ]]; then
  # 自己建的群組遇到區域不給用時，刪掉再改到 japaneast 重試；既有群組不重試
  if ! create_vm "$LOCATION" && [[ -z ${RG_EXISTS:-} ]]; then
    echo "$LOCATION 失敗，改用 japaneast"; LOCATION=japaneast
    az group delete -n "$RG" -y 2>/dev/null || true; create_vm "$LOCATION"
  fi
fi

# 在 VM 的網路安全群組（NSG）加規則，讓外部連到 80（HTTP，Let's Encrypt 驗證與轉址）與 443（HTTPS）
# 22 由 az vm create 自動開（default-allow-ssh）；--priority 是規則順序，不可重複
run az vm open-port -g "$RG" -n "$VM" --port 80 --priority 1001
run az vm open-port -g "$RG" -n "$VM" --port 443 --priority 1002
# 自動關機（az vm auto-shutdown）需要註冊 Microsoft.DevTestLab，課程訂閱沒有權限；不用時手動 az vm deallocate

HOST=$VM.$LOCATION.cloudapp.azure.com
echo "網域：$HOST"

# 產生部署專用金鑰（ed25519、沒有密碼）；已存在就沿用。GitHub Actions 用它 SSH 進 VM
[[ -f $KEY ]] || run ssh-keygen -t ed25519 -N '' -C gae265-deploy -f "$KEY"
# 把公鑰加到 VM 的 authorized_keys，持有私鑰的人才能登入
run ssh "$ADMIN@$HOST" "echo '$(cat "$KEY.pub")' >> ~/.ssh/authorized_keys"
# 印出要貼到 GitHub Environment secrets 的三個值
#   DEPLOY_KNOWN_HOSTS：VM 的 host key（ssh-keyscan 取得），讓 CI 能確認連到的是對的機器
echo; echo '--- DEPLOY_KNOWN_HOSTS ---'; ssh-keyscan -t ed25519 "$HOST" 2>/dev/null
#   DEPLOY_SSH_KEY：私鑰整份內容（不印出，用 pbcopy < 私鑰 複製）
echo; echo "--- DEPLOY_SSH_KEY ---（私鑰在 ${KEY}，整份貼上）"
#   DEPLOY_HOST：user@主機，make deploy 用它 SSH
echo "--- DEPLOY_HOST ---"; echo "$ADMIN@$HOST"
pause "到 GitHub → Settings → Environments 建立 production（deployment 只允許 main 與 v*），貼上上面三個 secret。"

# 在 VM 上用 Docker 官方腳本安裝 Docker，並把登入帳號加進 docker 群組（之後不用 sudo）
run ssh "$ADMIN@$HOST" 'curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER'
# 在 VM 上 clone repo（compose.prod.yaml 與 docker/db/init 從這裡讀），並複製 .env 範本
run ssh "$ADMIN@$HOST" 'git clone https://github.com/kurotyan514/gae265-03-group-project.git && cd gae265-03-group-project && cp .env.prod.example .env'
pause "ssh ${ADMIN}@${HOST}，編輯 ~/gae265-03-group-project/.env 填好所有必填設定（DOMAIN=${HOST}、PUBLIC_BASE_URL=https://${HOST} 等）。"
pause "到 Google Cloud Console 登記：https://$HOST/api/v1/auth/google/callback"
pause "到 GitHub Actions 手動執行 Deploy（main）。第一次會因 GHCR package 為 private 而部署失敗，屬預期。"
pause "把 GHCR 的 gae265-03-group-project-backend 與 -caddy 兩個 package 改成 public（Package settings → Change visibility），再重跑 Deploy。"

# 匯入 seed（條文、方案保費等）：在 backend 容器內執行；IMAGE_TAG 讓 compose 找到目前部署的版本
run ssh "$ADMIN@$HOST" 'cd gae265-03-group-project && IMAGE_TAG=$(git rev-parse HEAD) docker compose -f compose.prod.yaml exec backend python -m app.seed load'
echo "完成：https://${HOST}（embedding deployment 名稱不同時，seed 指令加 --as-model <名稱>）"
