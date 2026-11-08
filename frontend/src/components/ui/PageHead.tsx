import type { ReactNode } from "react";

/**
 * 頁面標題區（DESIGN.md 4.3）：麵包屑、H1、說明、小註。所有內頁開頭都用這個結構。
 * `title` 可以是文字或節點（例如「日本 2026/07/05～07/10」）。
 */
export function PageHead({
  crumb,
  title,
  meta,
  note,
}: {
  crumb?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  note?: ReactNode;
}) {
  return (
    <header>
      {crumb && <p className="t-label m-0 text-muted">{crumb}</p>}
      <h1 className="t-page-title mt-1 mb-0 text-heading">{title}</h1>
      {meta && <p className="t-meta mt-1.5 mb-0 text-muted">{meta}</p>}
      {note && <p className="t-caption mt-0.5 mb-0 text-muted">{note}</p>}
    </header>
  );
}
