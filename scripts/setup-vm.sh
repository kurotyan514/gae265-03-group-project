#!/usr/bin/env bash
# 首次架設正式環境 VM 的精靈：每一步先顯示指令，確認後才執行。細節見 docs/deploy.md
set -euo pipefail

RG=${RG:-gae265-03-group-project}
VM=${VM:-gae265-03}
ADMIN=${ADMIN:-azureuser}
LOCATION=${LOCATION:-eastasia}
KEY=${KEY:-$HOME/.ssh/gae265_deploy}

run() { # 顯示指令、確認後執行
  printf '\n$ %s\n' "$*"
  read -r -p '執行？[y/N] ' a
  if [[ $a == y ]]; then "$@"; else echo '（略過）'; fi
}
pause() { printf '\n%s\n' "$1"; read -r -p '完成後按 Enter…' _; }

command -v az >/dev/null || { echo '請先安裝 Azure CLI'; exit 1; }
az account show >/dev/null 2>&1 || run az login

create_vm() {
  az group create -n "$RG" -l "$1" >/dev/null || return
  az vm create -g "$RG" -n "$VM" -l "$1" --image Ubuntu2404 --size Standard_B2s \
    --admin-username "$ADMIN" --generate-ssh-keys \
    --public-ip-address-dns-name "$VM" --public-ip-sku Standard
}
printf '\n$ az group create + az vm create（%s，Standard_B2s，Ubuntu 2404）\n' "$LOCATION"
read -r -p '執行？[y/N] ' a
if [[ $a == y ]]; then
  create_vm "$LOCATION" || { echo "$LOCATION 失敗，改用 japaneast"; LOCATION=japaneast
    az group delete -n "$RG" -y 2>/dev/null || true; create_vm "$LOCATION"; }
fi
run az vm open-port -g "$RG" -n "$VM" --port 22 --priority 1000
run az vm open-port -g "$RG" -n "$VM" --port 80 --priority 1001
run az vm open-port -g "$RG" -n "$VM" --port 443 --priority 1002
# 台灣 23:00 = 15:00 UTC
run az vm auto-shutdown -g "$RG" -n "$VM" --time 1500

HOST=$VM.$LOCATION.cloudapp.azure.com
echo "網域：$HOST"

[[ -f $KEY ]] || run ssh-keygen -t ed25519 -N '' -C gae265-deploy -f "$KEY"
run ssh "$ADMIN@$HOST" "echo '$(cat "$KEY.pub")' >> ~/.ssh/authorized_keys"
echo; echo '--- DEPLOY_KNOWN_HOSTS ---'; ssh-keyscan -t ed25519 "$HOST" 2>/dev/null
echo; echo "--- DEPLOY_SSH_KEY ---（私鑰在 $KEY，整份貼上）"
echo "--- DEPLOY_HOST ---"; echo "$ADMIN@$HOST"
pause "到 GitHub → Settings → Environments 建立 production（deployment 只允許 main 與 v*），貼上上面三個 secret。"

run ssh "$ADMIN@$HOST" 'curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER'
run ssh "$ADMIN@$HOST" 'git clone https://github.com/kurotyan514/gae265-03-group-project.git && cd gae265-03-group-project && cp .env.prod.example .env'
pause "ssh $ADMIN@$HOST，編輯 ~/gae265-03-group-project/.env 填好所有必填設定（DOMAIN=$HOST、PUBLIC_BASE_URL=https://$HOST 等）。"
pause "到 Google Cloud Console 登記：https://$HOST/api/v1/auth/google/callback"
pause "到 GitHub Actions 手動執行 Deploy（main）。第一次會因 GHCR package 為 private 而部署失敗，屬預期。"
pause "把 GHCR 的 gae265-03-group-project-backend 與 -caddy 兩個 package 改成 public（Package settings → Change visibility），再重跑 Deploy。"

run ssh "$ADMIN@$HOST" 'cd gae265-03-group-project && IMAGE_TAG=$(git rev-parse HEAD) docker compose -f compose.prod.yaml exec backend python -m app.seed load'
echo "完成：https://$HOST（embedding deployment 名稱不同時，seed 指令加 --as-model <名稱>）"
