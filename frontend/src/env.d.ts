interface ImportMetaEnv {
  /** `"true"` 開啟假資料模式（MSW 攔下 `/api` 回假資料，只在開發用；`pnpm build` 固定關閉） */
  readonly VITE_MOCK: string;
}
