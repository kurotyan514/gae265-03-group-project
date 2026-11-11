import { Link } from "@tanstack/react-router";
import type { TodoView } from "../../client/types.gen";
import { btnSm, btnSmPri } from "../../components/ui/buttons";
import { PlaceholderButton } from "../../components/ui/PlaceholderButton";
import { Pill } from "../../components/ui/Tag";
import { card } from "./shared";

/**
 * 送件區（DESIGN.md 6.28）：左邊「送件」加狀態，右邊按鈕。
 * 還缺文件 → 「還缺 N 份文件」＋上傳文件；待辦沒勾完 → 說明；備齊 → 「文件已備齊」＋送件；
 * 已結案 → 說明文字，加反灰的「到 Gmail 查看」「下載全部文件」。
 */
export function SendBox({ id, todos, closed }: { id: string; todos: TodoView[]; closed: boolean }) {
  const active = todos.filter((t) => t.applicable !== false);
  const missingUploads = active.filter((t) => t.requires_upload && !t.is_done).length;
  const pending = active.filter((t) => !t.requires_upload && !t.is_done).length;

  return (
    <section
      className={`${card} flex flex-wrap items-center gap-x-5 gap-y-3`}
      aria-label="送件"
      data-testid="send-box"
    >
      <h2 className="m-0 text-xl font-bold text-heading">送件</h2>
      {closed ? (
        <>
          <p className="m-0 t-body text-muted" data-testid="send-closed">
            已送件結案，文件已存在你的 Google Drive。
          </p>
          <div className="ml-auto flex flex-wrap gap-3">
            <PlaceholderButton kind="small">到 Gmail 查看</PlaceholderButton>
            <PlaceholderButton kind="small">下載全部文件</PlaceholderButton>
          </div>
        </>
      ) : missingUploads > 0 ? (
        <>
          <Pill tone="need">還缺 {missingUploads} 份文件</Pill>
          <div className="ml-auto">
            {/* 上傳框就在這一頁待辦區上方，捲過去 */}
            <a href="#upload-box" className={btnSm}>
              上傳文件
            </a>
          </div>
        </>
      ) : pending > 0 ? (
        <>
          <Pill tone="need">還有 {pending} 項待辦沒完成</Pill>
          <p className="m-0 t-caption text-muted">勾完待辦後就能送件。</p>
        </>
      ) : (
        <>
          <Pill tone="sent">文件已備齊</Pill>
          <div className="ml-auto">
            <Link
              to="/incident/$id/submit"
              params={{ id }}
              className={btnSmPri}
              data-testid="go-submit"
            >
              送件
            </Link>
          </div>
        </>
      )}
    </section>
  );
}
