import { Button } from "@base-ui/react/button";
import { useState } from "react";
import type { ComparisonIn, ComparisonOut, Destination } from "../../client/types.gen";

// 原型順序；satisfies 讓產生的 Destination 型別多或少一個時編譯失敗
const DESTINATIONS = Object.keys({
  美國: 0,
  加拿大: 0,
  日本: 0,
  韓國: 0,
  新加坡: 0,
  英國: 0,
  歐洲申根國家: 0,
  澳洲: 0,
  紐西蘭: 0,
  中國大陸: 0,
  香港澳門: 0,
  泰國: 0,
  越南: 0,
  馬來西亞: 0,
  菲律賓: 0,
  印尼: 0,
} satisfies Record<Destination, 0>) as Destination[];

/** 瀏覽器本地日期的 YYYY-MM-DD，可以直接跟 `<input type="date">` 的值比大小。 */
function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 含頭尾的天數；兩個日期都當 UTC 午夜解析，相減不受夏令時間影響。 */
function tripDays(depart: string, ret: string): number {
  return (Date.parse(ret) - Date.parse(depart)) / 86_400_000 + 1;
}

/** 與後端 ComparisonIn 同一套規則與訊息（spec #75）。storedDepart：已存的出發日沒改時不擋「已過」。 */
function validate(
  depart: string,
  ret: string,
  age: string,
  storedDepart: string | undefined,
): string[] {
  const errors: string[] = [];
  if (depart && depart !== storedDepart && depart < today()) errors.push("出發日要從今天起。");
  if (depart && ret) {
    if (ret < depart) errors.push("回程日不能早於出發日。");
    else if (tripDays(depart, ret) < 4) errors.push("旅遊天數最短 4 天。");
    else if (tripDays(depart, ret) > 10) errors.push("旅遊天數最長 10 天。");
  }
  if (age && !(/^\d+$/.test(age) && Number(age) >= 15 && Number(age) <= 80)) {
    errors.push("年齡請填 15～80 的整數。");
  }
  return errors;
}

/** 後端錯誤轉成畫面文字：422 顯示各欄位的訊息，其他顯示 detail。 */
function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join(" ");
  if (typeof detail === "string") return detail;
  return "存檔失敗，請再試一次。";
}

const fieldClass = "mt-1 block w-full rounded-md border px-2 py-1";

/** 1-1 輸入旅遊背景的表單；新建與修改共用，存檔由呼叫端決定 POST 或 PATCH。 */
export function BackgroundForm({
  initial,
  onSubmit,
  pending,
  error,
}: {
  initial?: ComparisonOut;
  onSubmit: (body: ComparisonIn) => void;
  pending: boolean;
  error: unknown;
}) {
  const [destination, setDestination] = useState(initial?.destination ?? "");
  const [depart, setDepart] = useState(initial?.depart_date ?? "");
  const [ret, setRet] = useState(initial?.return_date ?? "");
  const [age, setAge] = useState(initial ? String(initial.age) : "");

  const errors = validate(depart, ret, age, initial?.depart_date);
  const complete = destination && depart && ret && age;

  return (
    <main className="max-w-md space-y-4">
      <div>
        <h1 className="text-2xl font-bold">這趟旅程</h1>
        <p className="text-gray-600">單人、國外旅遊</p>
      </div>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!complete || errors.length) return;
          onSubmit({
            destination: destination as Destination,
            depart_date: depart,
            return_date: ret,
            age: Number(age),
          });
        }}
      >
        <label className="block">
          目的地
          <select
            value={destination}
            onChange={(e) => setDestination(e.target.value as Destination)}
            className={fieldClass}
          >
            <option value="" disabled>
              請選擇
            </option>
            {DESTINATIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            出發日
            <input
              type="date"
              value={depart}
              onChange={(e) => setDepart(e.target.value)}
              className={fieldClass}
            />
          </label>
          <label className="block">
            回程日
            <input
              type="date"
              value={ret}
              onChange={(e) => setRet(e.target.value)}
              className={fieldClass}
            />
          </label>
        </div>
        <p data-testid="trip-days" className="text-gray-600">
          {depart && ret && ret >= depart
            ? `共 ${tripDays(depart, ret)} 天`
            : "選好兩個日期後顯示天數"}
        </p>
        <label className="block">
          年齡
          {/* 用 text：type="number" 遇到非數字會回空字串，就沒辦法顯示錯誤 */}
          <input
            type="text"
            inputMode="numeric"
            value={age}
            onChange={(e) => setAge(e.target.value)}
            aria-describedby="age-hint"
            className={fieldClass}
          />
          <span id="age-hint" className="text-sm text-gray-600">
            可輸入 15～80 歲
          </span>
        </label>
        {errors.length > 0 && (
          <ul role="alert" className="text-red-600">
            {errors.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        {error != null && (
          <p role="alert" className="text-red-600">
            {errorText(error)}
          </p>
        )}
        <Button
          type="submit"
          disabled={!complete || errors.length > 0 || pending}
          className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
        >
          下一步
        </Button>
      </form>
    </main>
  );
}
