# 正式環境：build 前端後交給 Caddy 提供靜態檔；build context 是 repo 根目錄
# Node 大版本、pnpm 大版本要與 mise.toml 一致
FROM node:24-slim AS frontend

RUN npm install -g pnpm@12

WORKDIR /app/frontend

# 先只裝依賴，改前端程式碼時重用這層
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm-store \
    pnpm install --frozen-lockfile --store-dir /pnpm-store

COPY frontend ./
# build script 固定 VITE_MOCK=false，產物不含 MSW
RUN pnpm build

FROM caddy:2-alpine

COPY docker/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/frontend/dist /srv
