import type { ReactNode } from "react";
import type { ClaimPackage } from "../../client/types.gen";
import { fieldInput } from "../../components/ui/Field";
import { splitBlanks } from "./blanks";

type FillProps = {
  /** 使用者填的內容，key 是項目（例如「被保險人姓名」）。 */
  values: Record<string, string>;
  /** 有給的話，空格變成輸入框；同一項目的輸入框共用一個值。 */
  onFill?: (item: string, value: string) => void;
};

/** 有空格的文字：「（請填寫＋項目）」標成黃底紅字，可以填的時候換成輸入框。 */
function WithBlanks({ text, values, onFill }: { text: string } & FillProps) {
  return (
    <>
      {splitBlanks(text).map((part, i) => {
        const item = part.blank;
        if (!item) {
          // biome-ignore lint/suspicious/noArrayIndexKey: 切出來的片段沒有其他穩定的 key
          return <span key={i}>{part.text}</span>;
        }
        if (onFill) {
          return (
            <input
              // biome-ignore lint/suspicious/noArrayIndexKey: 同上
              key={i}
              data-testid="blank"
              aria-label={item}
              placeholder={part.text}
              value={values[item] ?? ""}
              onChange={(e) => onFill(item, e.target.value)}
              size={Math.max(part.text.length * 2, 8)}
              className="mx-0.5 rounded-tag border border-sun bg-warn-soft px-1.5 py-0.5 text-danger-ink placeholder:text-danger"
            />
          );
        }
        return (
          <mark
            // biome-ignore lint/suspicious/noArrayIndexKey: 同上
            key={i}
            data-testid="blank"
            className="rounded-tag bg-warn-soft px-1 text-danger-ink"
          >
            {part.text}
          </mark>
        );
      })}
    </>
  );
}

type AddressProps = {
  /** 寄件者：使用者自己的 Gmail，只顯示、不能改。 */
  sender?: string;
  /** 收件者：使用者輸入的信箱。 */
  recipient?: string;
  /** 有給的話，收件者變成輸入框。 */
  onRecipient?: (value: string) => void;
};

/** 一列：左邊標籤（caption-bold、muted），右邊內容；手機改上下排。 */
function Row({
  label,
  children,
  warn = false,
}: {
  label: string;
  children: ReactNode;
  warn?: boolean;
}) {
  return (
    <div
      className={`grid grid-cols-1 items-start gap-1 border-b border-line px-4 py-3.5 last:border-b-0 md:grid-cols-[96px_1fr] md:gap-3 md:px-6 ${
        warn ? "bg-warn-soft" : ""
      }`}
    >
      <span className="t-caption-bold text-muted">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/**
 * 7 號產生的送件信（DESIGN.md 6.29 信件預覽）：收件者、寄件者、主旨、內文、附件逐列排。
 * 開發頁與正式送件頁共用。空格「（請填寫＋項目）」標成警示底，可以填的時候換成輸入框。
 */
export function ClaimLetter({
  pkg,
  values = {},
  onFill,
  sender,
  recipient = "",
  onRecipient,
}: { pkg: ClaimPackage } & Partial<FillProps> & AddressProps) {
  return (
    <article className="overflow-hidden rounded-2xl border border-line/60 bg-white shadow-card md:rounded-panel">
      {onRecipient ? (
        <Row label="收件者">
          <input
            type="email"
            value={recipient}
            onChange={(e) => onRecipient(e.target.value)}
            placeholder="保險公司的理賠信箱"
            aria-label="收件者"
            data-testid="letter-recipient"
            className={`${fieldInput} min-h-11! w-full py-2!`}
          />
        </Row>
      ) : (
        recipient && (
          <Row label="收件者">
            <span data-testid="letter-recipient">{recipient}</span>
          </Row>
        )
      )}
      {sender !== undefined && (
        <Row label="寄件者">
          <span data-testid="letter-sender">{sender}</span>
          <span className="text-muted">（你的 Gmail）</span>
        </Row>
      )}
      <Row label="主旨">
        <span data-testid="letter-subject">
          <WithBlanks text={pkg.subject} values={values} onFill={onFill} />
        </span>
      </Row>
      <Row label="內文">
        <pre data-testid="letter-body" className="m-0 font-sans leading-[26px] whitespace-pre-wrap">
          <WithBlanks text={pkg.body} values={values} onFill={onFill} />
        </pre>
      </Row>
      <Row label="附件">
        <p className="m-0 t-caption text-muted">共 {pkg.attachments?.length ?? 0} 份</p>
        <ul className="m-0 mt-1 list-none p-0">
          {(pkg.attachments ?? []).map((a) => (
            <li key={a.document_id} data-testid="attachment" className="t-caption-bold text-brand">
              📎 {a.file_name}
            </li>
          ))}
        </ul>
      </Row>
    </article>
  );
}
