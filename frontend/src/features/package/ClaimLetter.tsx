import type { ClaimPackage } from "../../client/types.gen";
import { splitBlanks } from "./blanks";

/** 有空格的文字：「（請填寫＋項目）」標成黃底紅字，讓使用者一眼看到要補的地方。 */
function WithBlanks({ text }: { text: string }) {
  return (
    <>
      {splitBlanks(text).map((part, i) =>
        part.blank ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: 切出來的片段沒有其他穩定的 key
          <mark key={i} data-testid="blank" className="rounded bg-yellow-200 px-0.5 text-red-700">
            {part.text}
          </mark>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: 同上
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

/** 7 號產生的送件信：主旨、內文、附件。開發頁與正式送件頁共用。 */
export function ClaimLetter({ pkg }: { pkg: ClaimPackage }) {
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <p>
        <span className="text-gray-500">主旨：</span>
        <span data-testid="letter-subject">
          <WithBlanks text={pkg.subject} />
        </span>
      </p>
      <pre data-testid="letter-body" className="font-sans whitespace-pre-wrap">
        <WithBlanks text={pkg.body} />
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
