import { createFileRoute } from "@tanstack/react-router";
import { IngestPage } from "../features/ingest/IngestPage";
import { type IngestSearch, validateIngestSearch } from "../features/ingest/search";

export const Route = createFileRoute("/dev/ingest")({
  // ?demo=1 開啟示範模式；?speed=2 調整示範的播放倍速（預設 1）
  validateSearch: validateIngestSearch,
  component: DevIngest,
});

/** 開發用入口（只在非 production 有）；正式的入口是登入後的 /admin/ingest，同一份畫面。 */
function DevIngest() {
  const { demo, speed } = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <IngestPage
      demo={demo === 1}
      speed={speed}
      onToggleDemo={() =>
        navigate({
          search: (prev: IngestSearch) => ({ ...prev, demo: demo === 1 ? undefined : 1 }),
        })
      }
    />
  );
}
