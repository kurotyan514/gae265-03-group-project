import { Link } from "@tanstack/react-router";
import type { TodoView } from "../../client/types.gen";
import { btnSm, btnSmPri } from "../../components/ui/buttons";
import { PlaceholderButton } from "../../components/ui/PlaceholderButton";
import { Pill } from "../../components/ui/Tag";
import { closedText, useClosedLinks } from "./closedLinks";
import { card } from "./shared";

/**
 * 送件區（DESIGN.md 6.28）：左邊「送件」加狀態，右邊按鈕。
 * 還缺文件 → 「還缺 N 份文件」＋上傳文件；待辦沒勾完 → 說明；備齊 → 「文件已備齊」＋送件；
 * 已結案 → 依結案時的選擇（寄出／建草稿／沒建草稿）與有沒有上傳文件說明；「到 Gmail 查看」打開那封信或那份草稿、
 * 「下載全部文件」打開 Google Drive 上的行程資料夾。拿不到連結（沒建草稿、沒上傳文件、沒授權）的維持反灰。
 */
export function SendBox({
  id,
  todos,
  closed,
  hasFiles,
}: {
  id: string;
  todos: TodoView[];
  closed: boolean;
  /** 這次理賠有沒有存到 Google Drive 的文件。 */
  hasFiles: boolean;
}) {
  const active = todos.filter((t) => t.applicable !== false);
  const missingUploads = active.filter((t) => t.requires_upload && !t.is_done).length;
  const pending = active.filter((t) => !t.requires_upload && !t.is_done).length;
  const links = useClosedLinks(id, closed);

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
            {closedText(links.closedAs, hasFiles)}
          </p>
          <div className="ml-auto flex flex-wrap gap-3">
            {links.gmailUrl ? (
              <a
                href={links.gmailUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={btnSm}
                data-testid="send-box-gmail"
              >
                到 Gmail 查看
              </a>
            ) : (
              <PlaceholderButton kind="small">到 Gmail 查看</PlaceholderButton>
            )}
            {hasFiles && links.driveUrl ? (
              <a
                href={links.driveUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={btnSm}
                data-testid="send-box-drive"
              >
                下載全部文件
              </a>
            ) : (
              <PlaceholderButton kind="small">下載全部文件</PlaceholderButton>
            )}
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
