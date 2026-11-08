import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPolicyManual, updatePolicy } from "../../client";
import {
  listPlanSumInsuredOptionsOptions,
  listPlansOptions,
  listPoliciesOptions,
} from "../../client/@tanstack/react-query.gen";
import type { PolicyOut, PolicyPatch, PolicyUploadOut } from "../../client/types.gen";
import { ActionBar } from "../../components/ui/ActionBar";
import { btnPri } from "../../components/ui/buttons";
import {
  Field,
  FieldError,
  FieldHint,
  FieldOk,
  FieldWarn,
  fieldInput,
  RequiredMark,
} from "../../components/ui/Field";
import { FileDrop, FilePickButton, PickedFile } from "../../components/ui/FileDrop";
import { Segmented } from "../../components/ui/Segmented";
import { useToast } from "../../components/ui/Toast";
import { DESTINATIONS } from "../compare/BackgroundForm";
import { IMPORT_HINT, type ImportedTrip, ImportFromComparison } from "./ImportFromComparison";
import { errorText } from "./shared";

/** 表單裡的值（都是字串，直接對應輸入框）。 */
type Values = {
  company: string;
  planId: string;
  sum: string;
  destination: string;
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
};

const EMPTY: Values = {
  company: "",
  planId: "",
  sum: "",
  destination: "",
  startDate: "",
  startTime: "",
  endDate: "",
  endTime: "",
};

/** 「建立新的保單」在「我的保單」下拉裡的值。 */
const NEW = "__new__";

/** API 給的是台北時間（+08:00），時分直接取字串，不經瀏覽器時區換算。 */
const clockOf = (iso: string | null) => (iso ? iso.slice(11, 16) : "");

function valuesOf(p: PolicyOut | PolicyUploadOut): Values {
  return {
    company: p.company,
    planId: p.plan_id,
    sum: p.sum_insured === null ? "" : String(p.sum_insured),
    destination: p.destination ?? "",
    startDate: p.start_date ?? "",
    startTime: clockOf(p.start_at),
    endDate: p.end_date ?? "",
    endTime: clockOf(p.end_at),
  };
}

type Mark = "auto" | "missing" | null;

/** 欄位旁的標記：讀到而且沒改過 → 由保單自動帶入；讀不到而且還是空的 → 請自行選擇；改過就不標。 */
function statusOf(edited: boolean, read: boolean, empty: boolean): Mark {
  if (edited) return null;
  if (read) return "auto";
  return empty ? "missing" : null;
}

function MarkNote({ id, status }: { id: string; status: Mark }) {
  if (status === "auto")
    return <FieldOk data-testid={`mark-${id}`}>由保單自動帶入，可修改</FieldOk>;
  if (status === "missing") {
    return <FieldWarn data-testid={`mark-${id}`}>保單上讀不到，請自行選擇</FieldWarn>;
  }
  return null;
}

type Source = "existing" | "upload" | "manual";

/**
 * 2-1 建立行程的保單表單（DESIGN.md 7.8）：選「我的保單」、上傳保單、或手動選擇，三條路用同一張表單。
 * 上傳結果直接填進欄位並標記哪些是讀到的；公司、方案只在手動時可以改。
 * 按「下一步」才存回（沒改的欄位不送），再交給 `onNext(policyId)`。
 */
export function PolicyStep({
  initialPolicyId,
  onError,
  onNext,
  back,
}: {
  /** 從 2-2 回來修改時帶的保單編號。 */
  initialPolicyId?: string;
  onError: (message: string | null) => void;
  onNext: (policyId: string) => void | Promise<void>;
  /** 上一步（回首頁）。 */
  back: ReactNode;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const policies = useQuery(listPoliciesOptions());
  const plans = useQuery(listPlansOptions());
  const list = policies.data ?? [];

  // 沒選過就用從 2-2 回來的那份、再不然最新的一份；都沒有就是建立新的
  const [choice, setChoice] = useState<string | null>(null);
  const selectedId = choice ?? initialPolicyId ?? list[0]?.id ?? NEW;
  const existing = selectedId === NEW ? undefined : list.find((p) => p.id === selectedId);

  const [newMode, setNewMode] = useState<"upload" | "manual">("upload");
  const [uploaded, setUploaded] = useState<PolicyUploadOut | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [imported, setImported] = useState(false);
  const [busy, setBusy] = useState(false);

  const [v, setV] = useState<Values>(EMPTY);
  const [initial, setInitial] = useState<Values>(EMPTY);
  const [read, setRead] = useState<Set<string>>(new Set());
  // 方案不在可選清單裡（保單專用方案）時，下拉仍要顯示它的名稱
  const [planName, setPlanName] = useState("");

  const source: Source = existing ? "existing" : uploaded ? "upload" : "manual";
  const locked = source !== "manual"; // 公司與方案只在手動時可以改（後端也不允許改既有保單的方案）

  // 切到某份既有保單時載入它的值；同一份只載一次，免得重新讀取列表時蓋掉旅客改到一半的內容
  const loadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!existing) return;
    if (loadedFor.current === existing.id) return;
    loadedFor.current = existing.id;
    const values = valuesOf(existing);
    setV(values);
    setInitial(values);
    setRead(new Set());
    setPlanName(existing.plan_name);
    setImported(false);
  }, [existing]);

  function startNew() {
    loadedFor.current = NEW;
    setV(EMPTY);
    setInitial(EMPTY);
    setRead(new Set());
    setPlanName("");
    setUploaded(null);
    setFileName(null);
    setImported(false);
  }

  function chooseSaved(id: string) {
    setChoice(id);
    if (id === NEW) startNew();
    else loadedFor.current = null; // 讓上面的 effect 載入
  }

  async function onFile(files: File[]) {
    const file = files[0];
    if (!file) return;
    setUploading(true);
    onError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch("/api/v1/policies", { method: "POST", body });
      const data = await response.json().catch(() => null);
      if (!response.ok) return onError(errorText(data, response.status));
      const policy = data as PolicyUploadOut;
      await queryClient.invalidateQueries({ queryKey: listPoliciesOptions().queryKey });
      // 保單已建立：留在「建立新的」，表單填入讀到的值並標記
      setChoice(NEW);
      loadedFor.current = NEW;
      const values = valuesOf(policy);
      setV(values);
      setInitial(values);
      setRead(new Set(policy.auto_filled));
      setPlanName(policy.plan_name);
      setUploaded(policy);
      setFileName(file.name);
    } catch {
      onError(errorText(undefined));
    } finally {
      setUploading(false);
    }
  }

  function applyTrip(trip: ImportedTrip) {
    const plan = plans.data?.find((p) => p.id === trip.planId);
    setV((cur) => ({
      ...cur,
      company: plan?.company ?? cur.company,
      planId: trip.planId,
      sum: String(trip.sumInsured),
      destination: trip.destination,
      startDate: trip.startDate,
      endDate: trip.endDate,
    }));
    setImported(true);
  }

  // 保額：有報價的方案用下拉；保單專用方案沒有報價，用數字輸入
  const sumOptions = useQuery({
    ...listPlanSumInsuredOptionsOptions({ path: { plan_id: v.planId } }),
    enabled: v.planId !== "",
  });
  const offered = sumOptions.data?.sum_insured ?? [];
  const hasQuotes = offered.length > 0;
  const loadingQuotes = v.planId !== "" && sumOptions.isPending;
  // 保單上讀到的保額不一定在報價裡：它要一直留在選項中，改選別的之後還能選回來
  const choices =
    initial.sum !== "" && initial.planId === v.planId && !offered.includes(Number(initial.sum))
      ? [Number(initial.sum), ...offered]
      : offered;

  const companies = useMemo(() => {
    const names = [...new Set((plans.data ?? []).map((p) => p.company))];
    return v.company && !names.includes(v.company) ? [v.company, ...names] : names;
  }, [plans.data, v.company]);
  const planChoices = useMemo(() => {
    const own = (plans.data ?? []).filter((p) => p.company === v.company);
    return v.planId && !own.some((p) => p.id === v.planId)
      ? [{ id: v.planId, name: planName }, ...own]
      : own;
  }, [plans.data, v.company, v.planId, planName]);

  const set = (patch: Partial<Values>) => setV((cur) => ({ ...cur, ...patch }));

  const sumEdited = v.sum !== initial.sum;
  const destinationEdited = v.destination !== initial.destination;
  const periodEdited =
    v.startDate !== initial.startDate ||
    v.startTime !== initial.startTime ||
    v.endDate !== initial.endDate ||
    v.endTime !== initial.endTime;
  const marking = source === "upload";
  const periodError =
    v.startDate && v.endDate && v.endDate < v.startDate ? "結束日不能早於開始日。" : "";
  // 必填的欄位：缺哪些就列哪些，「下一步」要全部填完才能按（前端阻擋，後端不另外擋；時間是選填）
  const missing = [
    v.company === "" && "保險公司",
    v.planId === "" && "方案",
    !/^[1-9]\d*$/.test(v.sum) && "保額",
    v.destination.trim() === "" && "目的地",
    v.startDate === "" && "開始日",
    v.endDate === "" && "結束日",
  ].filter((x): x is string => x !== false);
  const complete = missing.length === 0 && !periodError;

  function patchOf(base: Values): PolicyPatch {
    // 只送改過的欄位：沒動的時間不重送，免得秒數被截掉；後端沒帶的欄位不動
    const patch: PolicyPatch = {};
    if (v.sum !== base.sum) patch.sum_insured = v.sum === "" ? null : Number(v.sum);
    if (v.destination !== base.destination) patch.destination = v.destination.trim() || null;
    if (v.startDate !== base.startDate) patch.start_date = v.startDate || null;
    if (v.endDate !== base.endDate) patch.end_date = v.endDate || null;
    if (v.startTime !== base.startTime) patch.start_time = v.startTime ? `${v.startTime}:00` : null;
    if (v.endTime !== base.endTime) patch.end_time = v.endTime ? `${v.endTime}:00` : null;
    return patch;
  }

  async function next() {
    if (!complete || busy) return;
    setBusy(true);
    onError(null);
    try {
      let policyId = existing?.id ?? uploaded?.id ?? "";
      let base = initial;
      if (source === "manual") {
        // 手動：先建立保單（只收方案、保額與期間），目的地與時間再用修改補上
        const created = await createPolicyManual({
          body: {
            plan_id: v.planId,
            sum_insured: Number(v.sum),
            start_date: v.startDate,
            end_date: v.endDate,
          },
        });
        if (!created.data) return onError(errorText(created.error, created.response?.status));
        policyId = created.data.id;
        base = valuesOf(created.data);
      }
      const patch = patchOf(base);
      if (Object.keys(patch).length > 0) {
        const res = await updatePolicy({ path: { policy_id: policyId }, body: patch });
        if (!res.data) return onError(errorText(res.error, res.response?.status));
      }
      await queryClient.invalidateQueries({ queryKey: listPoliciesOptions().queryKey });
      toast.show("已存檔");
      await onNext(policyId);
    } catch {
      onError(errorText(undefined));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void next();
      }}
      className="flex flex-col gap-6"
      data-testid="trip-form"
    >
      <div className="flex flex-col gap-6 rounded-2xl border border-line/60 bg-white p-5 shadow-card md:rounded-panel md:px-8 md:py-7">
        {list.length > 0 && (
          <Field label="我的保單" htmlFor="my-policy">
            <select
              id="my-policy"
              value={selectedId}
              onChange={(e) => chooseSaved(e.target.value)}
              className={`${fieldInput} w-full`}
              data-testid="policy"
            >
              {list.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
              <option value={NEW}>建立新的保單（上傳或手動選擇）</option>
            </select>
          </Field>
        )}

        {selectedId === NEW && (
          <>
            <Segmented
              label="建立保單的方式"
              value={newMode}
              onChange={setNewMode}
              options={[
                { value: "upload", label: "上傳保單", testId: "mode-upload" },
                { value: "manual", label: "手動選擇", testId: "mode-manual" },
              ]}
            />
            {newMode === "upload" ? (
              <div className="flex flex-col gap-3">
                <FileDrop
                  title="上傳保單"
                  description="PDF（文字型），10 MB 內。個資會先移除再讀取，原檔不保存。"
                >
                  <FilePickButton
                    label={uploading ? "讀取中…" : "選擇保單檔案"}
                    accept="application/pdf"
                    disabled={uploading}
                    onFiles={(files) => void onFile(files)}
                    inputTestId="policy-file"
                  />
                  {fileName && <PickedFile name={fileName} />}
                </FileDrop>
                {uploaded && <UploadedSummary policy={uploaded} />}
              </div>
            ) : (
              <>
                <ImportFromComparison onPick={applyTrip} />
                {imported && <FieldWarn data-testid="import-hint">{IMPORT_HINT}</FieldWarn>}
              </>
            )}
          </>
        )}

        <div className="grid gap-5 md:grid-cols-2">
          <Field label="保險公司" htmlFor="trip-company" required>
            <select
              id="trip-company"
              value={v.company}
              disabled={locked}
              onChange={(e) => set({ company: e.target.value, planId: "", sum: "" })}
              className={fieldInput}
              aria-required="true"
              data-testid="confirm-company"
            >
              <option value="">請選擇</option>
              {companies.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="方案" htmlFor="trip-plan" required>
            <select
              id="trip-plan"
              value={v.planId}
              disabled={locked || v.company === ""}
              onChange={(e) => set({ planId: e.target.value, sum: "" })}
              className={fieldInput}
              aria-required="true"
              data-testid="confirm-plan"
            >
              <option value="">{v.company === "" ? "先選保險公司" : "請選擇"}</option>
              {planChoices.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {!locked && <FieldHint>可在投保確認信或保單上找到方案與保額</FieldHint>}
          </Field>
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          <Field label="保額（身故及失能，元）" htmlFor="confirm-sum-insured" required>
            {v.planId === "" ? (
              <select
                disabled
                className={fieldInput}
                id="confirm-sum-insured"
                data-testid="confirm-sum-insured"
              >
                <option>先選方案</option>
              </select>
            ) : loadingQuotes ? (
              <select
                disabled
                className={fieldInput}
                id="confirm-sum-insured"
                data-testid="confirm-sum-insured"
              >
                <option>載入保額選項…</option>
              </select>
            ) : hasQuotes ? (
              <select
                value={v.sum}
                onChange={(e) => set({ sum: e.target.value })}
                className={fieldInput}
                id="confirm-sum-insured"
                data-testid="confirm-sum-insured"
              >
                {v.sum === "" && <option value="">請選擇</option>}
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
                value={v.sum}
                onChange={(e) => set({ sum: e.target.value })}
                className={fieldInput}
                id="confirm-sum-insured"
                data-testid="confirm-sum-insured"
              />
            )}
            {marking && (
              <MarkNote
                id="sum_insured"
                status={statusOf(sumEdited, read.has("sum_insured"), v.sum === "")}
              />
            )}
          </Field>
          <Field label="目的地" htmlFor="trip-destination" required>
            <input
              id="trip-destination"
              list="trip-destinations"
              value={v.destination}
              onChange={(e) => set({ destination: e.target.value })}
              placeholder="請選擇或輸入"
              className={fieldInput}
              aria-required="true"
              data-testid="confirm-destination"
            />
            <datalist id="trip-destinations">
              {DESTINATIONS.map((d) => (
                <option key={d} value={d} />
              ))}
            </datalist>
            {marking && (
              <MarkNote
                id="destination"
                status={statusOf(destinationEdited, read.has("destination"), v.destination === "")}
              />
            )}
          </Field>
        </div>

        <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
          <legend className="mb-2 p-0 t-label text-heading">
            保險期間（台灣時間）
            <RequiredMark />
          </legend>
          <div className="grid gap-5 md:grid-cols-2">
            <div className="flex gap-2">
              <input
                type="date"
                aria-label="開始日"
                value={v.startDate}
                onChange={(e) => set({ startDate: e.target.value })}
                className={`${fieldInput} min-w-0 flex-1`}
                data-testid="confirm-start-date"
              />
              <input
                type="time"
                aria-label="開始時間（選填）"
                value={v.startTime}
                onChange={(e) => set({ startTime: e.target.value })}
                className={fieldInput}
                data-testid="confirm-start-time"
              />
            </div>
            <div className="flex gap-2">
              <input
                type="date"
                aria-label="結束日"
                value={v.endDate}
                onChange={(e) => set({ endDate: e.target.value })}
                className={`${fieldInput} min-w-0 flex-1`}
                data-testid="confirm-end-date"
              />
              <input
                type="time"
                aria-label="結束時間（選填）"
                value={v.endTime}
                onChange={(e) => set({ endTime: e.target.value })}
                className={fieldInput}
                data-testid="confirm-end-time"
              />
            </div>
          </div>
          {marking && (
            <MarkNote
              id="period"
              status={statusOf(
                periodEdited,
                read.has("period"),
                v.startDate === "" && v.endDate === "",
              )}
            />
          )}
          <FieldHint>開始日與結束日必填，幾點幾分選填。</FieldHint>
          <FieldError data-testid="period-error">{periodError}</FieldError>
        </fieldset>
      </div>

      {missing.length > 0 && (
        <p role="status" className="m-0 t-caption text-warn" data-testid="missing-fields">
          還要填：{missing.join("、")}。
        </p>
      )}
      <ActionBar twoColumns>
        {back}
        <ActionBar.Push>
          <ActionBar.Full>
            <button
              type="submit"
              disabled={!complete || busy || uploading}
              className={btnPri}
              data-testid="confirm-continue"
            >
              下一步
            </button>
          </ActionBar.Full>
        </ActionBar.Push>
      </ActionBar>
    </form>
  );
}

/** 上傳後讀到的商品名稱、涵蓋險種與附加條款（唯讀，一行小字）。 */
function UploadedSummary({ policy }: { policy: PolicyUploadOut }) {
  return (
    <div className="flex flex-col gap-1 t-caption text-muted" data-testid="uploaded-summary">
      {policy.product_name && (
        <p className="m-0" data-testid="confirm-product-name">
          保單上的商品名稱：{policy.product_name}
        </p>
      )}
      <p className="m-0" data-testid="confirm-insurances">
        含的險種：{policy.insurances.map((i) => i.name).join("、")}
        {policy.addons.length > 0 &&
          `；加購：${policy.addons.map((a) => `${a.name}${a.section ? `（${a.section}）` : ""}`).join("、")}`}
      </p>
      {policy.riders.length > 0 && (
        <p className="m-0" data-testid="confirm-riders">
          適用附加條款：{policy.riders.join("、")}
        </p>
      )}
    </div>
  );
}
