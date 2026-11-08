import { createFileRoute } from "@tanstack/react-router";
import { RulesBrowser } from "../features/rules/RulesBrowser";

export const Route = createFileRoute("/dev/rules")({
  component: DevRules,
});

/** 開發用：唯讀瀏覽資料庫裡全部條文（含向量狀態）。要修改條文請用後台 /admin/rules。 */
function DevRules() {
  return <RulesBrowser source="dev" />;
}
