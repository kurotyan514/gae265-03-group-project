# 開發用：只提供 Node 與 pnpm，程式碼與 node_modules 由 compose bind mount 進來
# 不放在 frontend/ 底下，build context 才不會把 node_modules 整包送進 Docker
# Node 大版本、pnpm 大版本要與 mise.toml 一致
FROM node:24-slim

RUN npm install -g pnpm@12

WORKDIR /app/frontend
