import type { ClaimPackage } from "../../client/types.gen";
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
              className="mx-0.5 rounded border border-yellow-400 bg-yellow-100 px-1 text-red-700 placeholder:text-red-400"
            />
          );
        }
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: 同上
          <mark key={i} data-testid="blank" className="rounded bg-yellow-200 px-0.5 text-red-700">
            {part.text}
          </mark>
        );
      })}
    </>
  );
}

/** 7 號產生的送件信：主旨、內文、附件。開發頁與正式送件頁共用。 */
export function ClaimLetter({
  pkg,
  values = {},
  onFill,
}: { pkg: ClaimPackage } & Partial<FillProps>) {
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <p>
        <span className="text-gray-500">主旨：</span>
        <span data-testid="letter-subject">
          <WithBlanks text={pkg.subject} values={values} onFill={onFill} />
        </span>
      </p>
      <pre data-testid="letter-body" className="font-sans whitespace-pre-wrap">
        <WithBlanks text={pkg.body} values={values} onFill={onFill} />
      </pre>
      <div>
        <p className="text-gray-500">附件（{pkg.attachments?.length ?? 0}）</p>
        <ul className="list-disc pl-5">
          {(pkg.attachments ?? []).map((a) => (
            <li key={a.document_id} data-testid="attachment">
              {a.file_name}
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}
