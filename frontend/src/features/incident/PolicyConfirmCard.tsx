import { Button } from "@base-ui/react/button";
import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { updatePolicy } from "../../client";
import { listPlanSumInsuredOptionsOptions } from "../../client/@tanstack/react-query.gen";
import type { PolicyOut, PolicyPatch, PolicyUploadOut } from "../../client/types.gen";
import { box, errorText, input, primary } from "./shared";

type Status = "auto" | "missing" | null;

/** 欄位旁的標記：讀到而且沒改過 → 由保單自動帶入；讀不到而且還是空的 → 請自行填寫；改過就不標。 */
function Mark({ id, status }: { id: string; status: Status }) {
  if (status === null) return null;
  return (
    <small
      data-testid={`mark-${id}`}
      className={`block text-xs ${status === "auto" ? "text-green-700" : "text-amber-700"}`}
    >
      {status === "auto" ? "✓ 由保單自動帶入，可修改" : "保單上讀不到，請自行填寫"}
    </small>
  );
}

/** API 給的是台北時間（+08:00），時分直接取字串，不經瀏覽器時區換算。 */
const clockOf = (iso: string | null) => (iso ? iso.slice(11, 16) : "");

function statusOf(edited: boolean, read: boolean, empty: boolean): Status {
  if (edited) return null;
  if (read) return "auto";
  return empty ? "missing" : null;
}

/**
 * 上傳保單後的確認卡：顯示系統讀到的內容。公司、方案、險種與附加條款唯讀；
 * 保額、目的地與保險期間可以修改，按「確認，繼續」才存回（沒改就不呼叫 API）。
 */
export function PolicyConfirmCard({
  policy,
  onConfirmed,
  onError,
}: {
  policy: PolicyUploadOut;
  onConfirmed: (policy: PolicyOut) => void | Promise<void>;
  onError: (message: string | null) => void;
}) {
  const initial = {
    sum: policy.sum_insured === null ? "" : String(policy.sum_insured),
    destination: policy.destination ?? "",
    startDate: policy.start_date ?? "",
    startTime: clockOf(policy.start_at),
    endDate: policy.end_date ?? "",
    endTime: clockOf(policy.end_at),
  };
  const [sum, setSum] = useState(initial.sum);
  const [destination, setDestination] = useState(initial.destination);
  const [startDate, setStartDate] = useState(initial.startDate);
  const [startTime, setStartTime] = useState(initial.startTime);
  const [endDate, setEndDate] = useState(initial.endDate);
  const [endTime, setEndTime] = useState(initial.endTime);
  const [busy, setBusy] = useState(false);

  // 有報價的方案用下拉；保單專用方案沒有報價，用數字輸入。保單上讀到的保額不在報價裡時也要留著
  const options = useQuery(listPlanSumInsuredOptionsOptions({ path: { plan_id: policy.plan_id } }));
  const offered = options.data?.sum_insured ?? [];
  const hasQuotes = offered.length > 0;
  const loadingQuotes = options.isPending;
  // 保單上讀到的保額不一定在報價裡：它要一直留在選項中，改選別的之後還能選回來
  const choices =
    initial.sum !== "" && !offered.includes(Number(initial.sum))
      ? [Number(initial.sum), ...offered]
      : offered;

  const read = new Set(policy.auto_filled);
  const sumEdited = sum !== initial.sum;
  const destinationEdited = destination !== initial.destination;
  const periodEdited =
    startDate !== initial.startDate ||
    startTime !== initial.startTime ||
    endDate !== initial.endDate ||
    endTime !== initial.endTime;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (sum !== "" && !/^[1-9]\d*$/.test(sum)) {
      return onError("保額請填正整數（元）。");
    }
    // 只送改過的欄位：沒動的時間不重送，免得秒數被截掉；後端沒帶的欄位不動
    const patch: PolicyPatch = {};
    if (sumEdited) patch.sum_insured = sum === "" ? null : Number(sum);
    if (destinationEdited) patch.destination = destination.trim() || null;
    if (startDate !== initial.startDate) patch.start_date = startDate || null;
    if (endDate !== initial.endDate) patch.end_date = endDate || null;
    if (startTime !== initial.startTime) patch.start_time = startTime ? `${startTime}:00` : null;
    if (endTime !== initial.endTime) patch.end_time = endTime ? `${endTime}:00` : null;
    setBusy(true);
    onError(null);
    try {
      if (Object.keys(patch).length === 0) return await onConfirmed(policy);
      const res = await updatePolicy({ path: { policy_id: policy.id }, body: patch });
      if (!res.data) return onError(errorText(res.error, res.response?.status));
      await onConfirmed(res.data);
    } catch {
      onError(errorText(undefined));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className={box} data-testid="confirm-card" aria-label="確認保單內容">
      <h3 className="font-bold">確認系統讀到的保單內容</h3>
      <p className="text-xs text-gray-500">
        請對照手上的保單。讀錯的地方可以直接修改，沒問題就按「確認，繼續」。
      </p>

      <dl className="space-y-2">
        <div>
          <dt className="text-sm font-medium">保險公司</dt>
          <dd data-testid="confirm-company">{policy.company}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium">保險方案</dt>
          <dd data-testid="confirm-plan">{policy.plan_name}</dd>
          {policy.product_name && (
            <dd className="text-xs text-gray-500" data-testid="confirm-product-name">
              保單上的商品名稱：{policy.product_name}
            </dd>
          )}
        </div>
        <div>
          <dt className="text-sm font-medium">含的險種</dt>
          <dd className="text-sm" data-testid="confirm-insurances">
            {policy.insurances.map((i) => i.name).join("、")}
            {policy.addons.length > 0 &&
              `；加購：${policy.addons.map((a) => `${a.name}${a.section ? `（${a.section}）` : ""}`).join("、")}`}
          </dd>
        </div>
        {policy.riders.length > 0 && (
          <div>
            <dt className="text-sm font-medium">適用附加條款</dt>
            <dd data-testid="confirm-riders">
              <ul className="list-disc pl-5 text-sm">
                {policy.riders.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>

      <div className="space-y-1">
        <label htmlFor="confirm-sum-insured" className="block text-sm font-medium">
          保額（身故及失能，元）
        </label>
        {loadingQuotes ? (
          <select
            disabled
            className={`${input} w-full`}
            id="confirm-sum-insured"
            data-testid="confirm-sum-insured"
          >
            <option>載入保額選項…</option>
          </select>
        ) : hasQuotes ? (
          <select
            value={sum}
            onChange={(e) => setSum(e.target.value)}
            className={`${input} w-full`}
            id="confirm-sum-insured"
            data-testid="confirm-sum-insured"
          >
            {sum === "" && <option value="">請選擇</option>}
            {choices.map((n) => (
              <option key={n} value={n}>
                {n.toLocaleString()} 元
              </option>
            ))}
          </select>
        ) : (
          <input
            type="number"
            min={1}
            step={1}
            value={sum}
            onChange={(e) => setSum(e.target.value)}
            className={`${input} w-full`}
            id="confirm-sum-insured"
            data-testid="confirm-sum-insured"
          />
        )}
        <Mark id="sum_insured" status={statusOf(sumEdited, read.has("sum_insured"), sum === "")} />
      </div>

      <label className="block space-y-1">
        <span className="block text-sm font-medium">目的地</span>
        <input
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          className={`${input} w-full`}
          data-testid="confirm-destination"
        />
        <Mark
          id="destination"
          status={statusOf(destinationEdited, read.has("destination"), destination === "")}
        />
      </label>

      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">保險期間（台灣時間）</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="flex gap-2">
            <input
              type="date"
              aria-label="開始日"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className={`${input} min-w-0 flex-1`}
              data-testid="confirm-start-date"
            />
            <input
              type="time"
              aria-label="開始時間"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className={input}
              data-testid="confirm-start-time"
            />
          </div>
          <div className="flex gap-2">
            <input
              type="date"
              aria-label="結束日"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className={`${input} min-w-0 flex-1`}
              data-testid="confirm-end-date"
            />
            <input
              type="time"
              aria-label="結束時間"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className={input}
              data-testid="confirm-end-time"
            />
          </div>
        </div>
        <Mark
          id="period"
          status={statusOf(periodEdited, read.has("period"), startDate === "" && endDate === "")}
        />
      </fieldset>

      <Button type="submit" disabled={busy} className={primary} data-testid="confirm-continue">
        確認，繼續
      </Button>
    </form>
  );
}
