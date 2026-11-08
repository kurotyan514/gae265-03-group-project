/**
 * 按鈕的樣式（DESIGN.md 6.1、6.2）。按鈕一律白底：主要按鈕是 2px 品牌色框，不是實心填色。
 * 一頁只有一個主要動作，放在動作列最右邊（`ActionBar.Push`）。
 *
 * 每個變體都是**一整串** class，不要把兩個變體疊在一起：Tailwind 同一個屬性的 class 誰贏
 * 取決於產生的 CSS 順序，不是寫在 class 裡的順序（例如 `border-line` 與 `border-brand`）。
 * 用法：`<Button className={btn}>`、`<Button className={btnPri}>`、`<Link className={lnk}>`。
 */
const focus = "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf";
const disabled =
  "disabled:cursor-not-allowed disabled:opacity-40 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40";
const common = `inline-flex items-center justify-center gap-1.5 whitespace-nowrap bg-white text-brand ${disabled} ${focus}`;
/** 一般大小：高 48、圓角 12；手機的字比桌機小一級（t-btn）。 */
const medium = "min-h-12 rounded-btn px-4 t-btn md:px-7";
/** 小：高 36、圓角 10、caption-bold。 */
const small = "min-h-9 rounded-tag px-4 text-sm leading-[22px] font-bold";

/** 預設按鈕：1px 框線；hover 框線變品牌色。 */
export const btn = `${common} ${medium} border border-line hover:border-brand`;
/** 主要按鈕：2px 品牌色框。 */
export const btnPri = `${common} ${medium} border-2 border-brand`;
/** 小按鈕（預設與主要）。 */
export const btnSm = `${common} ${small} border border-line hover:border-brand`;
export const btnSmPri = `${common} ${small} border-2 border-brand`;
/** 滿寬：加在上面任一個後面（只動寬度，不衝突）。 */
export const wide = "w-full";

/** 文字連結：無框無底，綠色文字用 leaf-text（對比夠）。 */
export const lnk = `inline-flex items-center gap-1.5 text-left t-label text-leaf-text hover:underline hover:underline-offset-[3px] ${focus}`;
