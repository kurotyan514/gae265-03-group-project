import { Button } from "@base-ui/react/button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { createIncident, createPolicyManual } from "../client";
import {
  listIncidentsOptions,
  listPlanSumInsuredOptionsOptions,
  listPlansOptions,
  listPoliciesOptions,
} from "../client/@tanstack/react-query.gen";
import type { PolicyOut, PolicyUploadOut } from "../client/types.gen";
import {
  IMPORT_HINT,
  type ImportedTrip,
  ImportFromComparison,
} from "../features/incident/ImportFromComparison";
import { PolicyConfirmCard } from "../features/incident/PolicyConfirmCard";
import { box, errorText, input, primary, secondary } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/new")({
  component: NewIncidentPage,
});

type Mode = "choose" | "upload" | "confirm" | "manual";

/** 出事了的入口：先有一份保單（選現有的、上傳、或自己選方案與保額），再說明發生了什麼事。 */
function NewIncidentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const policies = useQuery(listPoliciesOptions());
  const incidents = useQuery(listIncidentsOptions());
  const [mode, setMode] = useState<Mode>("choose");
  const [policyId, setPolicyId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [destination, setDestination] = useState("");
  const [uploaded, setUploaded] = useState<PolicyUploadOut | null>(null);

  const list = policies.data ?? [];
  const selected = policyId || list[0]?.id || "";

  async function onCreated(policy: PolicyOut) {
    await queryClient.invalidateQueries({ queryKey: listPoliciesOptions().queryKey });
    setPolicyId(policy.id);
    setMode("choose");
  }

  /** 上傳成功：保單已建立，先讓旅客確認系統讀到的內容。 */
  async function onUploaded(policy: PolicyUploadOut) {
    await queryClient.invalidateQueries({ queryKey: listPoliciesOptions().queryKey });
    setUploaded(policy);
    setMode("confirm");
  }

  /** 確認（或修改）完畢：選好這份保單，目的地帶到下一步。 */
  async function onConfirmed(policy: PolicyOut) {
    // 保單有目的地才帶入；沒有就保留旅客已經填的（或從比較帶入的）目的地
    if (policy.destination) setDestination(policy.destination);
    setUploaded(null);
    await onCreated(policy);
  }

  async function start(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    const res = await createIncident({
      path: { policy_id: selected },
      body: {
        description: String(form.get("description")),
        destination: String(form.get("destination") || "") || null,
      },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    await navigate({ to: "/incident/$id", params: { id: res.data.incident.incident_id } });
  }

  return (
    <main className="space-y-6">
      <h1 className="text-2xl font-bold">出事了：幫我處理理賠</h1>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-red-800" data-testid="error">
          {error}
        </p>
      )}

      <section className={box} aria-label="保單">
        <h2 className="font-bold">1. 哪一份保單？</h2>
        {mode === "choose" && (
          <>
            {list.length > 0 && (
              <label className="block space-y-1">
                <span className="block text-sm font-medium">我的保單</span>
                <select
                  value={selected}
                  onChange={(e) => {
                    setPolicyId(e.target.value);
                    // 改選保單時目的地預設成那份保單的；保單沒有就保留已填的
                    const dest = list.find((p) => p.id === e.target.value)?.destination;
                    if (dest) setDestination(dest);
                  }}
                  className={`${input} w-full`}
                  data-testid="policy"
                >
                  {list.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {list.length === 0 && !policies.isPending && (
              <p className="text-sm text-gray-600">還沒有保單。上傳保單，或自己選方案與保額。</p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                className={secondary}
                onClick={() => setMode("upload")}
                data-testid="mode-upload"
              >
                上傳保單
              </Button>
              <Button
                type="button"
                className={secondary}
                onClick={() => setMode("manual")}
                data-testid="mode-manual"
              >
                選方案與保額
              </Button>
            </div>
          </>
        )}
        {mode === "upload" && (
          <UploadPolicy onDone={onUploaded} onCancel={() => setMode("choose")} onError={setError} />
        )}
        {mode === "confirm" && uploaded && (
          <PolicyConfirmCard policy={uploaded} onConfirmed={onConfirmed} onError={setError} />
        )}
        {mode === "manual" && (
          <ManualPolicy
            onDone={onCreated}
            onCancel={() => setMode("choose")}
            onError={setError}
            onDestination={setDestination}
          />
        )}
      </section>

      {mode === "choose" && (
        <form onSubmit={start} className={box} data-testid="start-form">
          <h2 className="font-bold">2. 發生了什麼事？</h2>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">簡單說明</span>
            <textarea
              name="description"
              required
              rows={3}
              placeholder="例如：班機延誤了六小時"
              className={`${input} w-full`}
            />
          </label>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">目的地（選填）</span>
            <input
              name="destination"
              key={destination}
              defaultValue={destination}
              className={`${input} w-full`}
            />
          </label>
          <Button
            type="submit"
            disabled={busy || !selected}
            className={primary}
            data-testid="start"
          >
            開始處理
          </Button>
          {!selected && <p className="text-sm text-gray-500">先選好保單才能開始。</p>}
        </form>
      )}

      <section className={box} aria-label="進行中的事件">
        <h2 className="font-bold">我的事件</h2>
        <ul className="space-y-1" data-testid="incidents">
          {incidents.data?.length === 0 && <li className="text-gray-500">還沒有事件</li>}
          {incidents.data?.map((i) => (
            <li key={i.id}>
              <Link
                to="/incident/$id"
                params={{ id: i.id }}
                className="block rounded-md border px-2 py-1 hover:bg-gray-100"
              >
                {i.title}
                <span className="block text-xs text-gray-500">
                  {i.incident_type_name ?? "類型確認中"} ·{" "}
                  {i.status === "completed" ? "已完成" : "進行中"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

type PolicyFormProps<T = PolicyOut> = {
  onDone: (policy: T) => void | Promise<void>;
  onCancel: () => void;
  onError: (message: string | null) => void;
};

/** 上傳保單 PDF，後端比對方案；比對不到會說明原因。 */
function UploadPolicy({ onDone, onCancel, onError }: PolicyFormProps<PolicyUploadOut>) {
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    onError(null);
    try {
      const response = await fetch("/api/v1/policies", {
        method: "POST",
        body: new FormData(e.currentTarget),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) return onError(errorText(body, response.status));
      await onDone(body as PolicyUploadOut);
    } catch {
      onError(errorText(undefined));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2" data-testid="upload-policy-form">
      <label className="block space-y-1">
        <span className="block text-sm font-medium">保單 PDF（文字型）</span>
        <input
          type="file"
          name="file"
          accept="application/pdf"
          required
          data-testid="policy-file"
        />
      </label>
      <p className="text-xs text-gray-500">
        系統只記下比對到的方案、保額、目的地與保險期間，不保存 PDF；上傳後會先請你確認讀到的內容。
      </p>
      <div className="flex gap-2">
        <Button type="submit" disabled={busy} className={primary} data-testid="upload-policy">
          上傳
        </Button>
        <Button type="button" onClick={onCancel} className={secondary}>
          取消
        </Button>
      </div>
    </form>
  );
}

/** 沒有保單 PDF：選方案與保額，保險期間選填。 */
function ManualPolicy({
  onDone,
  onCancel,
  onError,
  onDestination,
}: PolicyFormProps & { onDestination: (destination: string) => void }) {
  const plans = useQuery(listPlansOptions());
  const [planId, setPlanId] = useState("");
  const [sumInsured, setSumInsured] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [imported, setImported] = useState(false);

  function applyTrip(trip: ImportedTrip) {
    setPlanId(trip.planId);
    setSumInsured(String(trip.sumInsured));
    setStartDate(trip.startDate);
    setEndDate(trip.endDate);
    onDestination(trip.destination);
    setImported(true);
  }
  const options = useQuery({
    ...listPlanSumInsuredOptionsOptions({ path: { plan_id: planId } }),
    enabled: planId !== "",
  });
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    onError(null);
    const res = await createPolicyManual({
      body: {
        plan_id: planId,
        sum_insured: Number(form.get("sum_insured")),
        start_date: String(form.get("start_date") || "") || null,
        end_date: String(form.get("end_date") || "") || null,
      },
    });
    setBusy(false);
    if (!res.data) return onError(errorText(res.error, res.response?.status));
    await onDone(res.data);
  }

  return (
    <form onSubmit={submit} className="space-y-2" data-testid="manual-policy-form">
      <ImportFromComparison onPick={applyTrip} />
      {imported && (
        <p className="text-sm text-amber-700" data-testid="import-hint">
          {IMPORT_HINT}
        </p>
      )}
      <label className="block space-y-1">
        <span className="block text-sm font-medium">保險方案</span>
        <select
          value={planId}
          onChange={(e) => {
            setPlanId(e.target.value);
            setSumInsured("");
          }}
          required
          className={`${input} w-full`}
          data-testid="manual-plan"
        >
          <option value="">請選擇</option>
          {plans.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block space-y-1">
        <span className="block text-sm font-medium">保額（身故保額）</span>
        <select
          name="sum_insured"
          value={sumInsured}
          onChange={(e) => setSumInsured(e.target.value)}
          required
          disabled={planId === "" || options.isPending}
          className={`${input} w-full`}
          data-testid="manual-sum-insured"
        >
          <option value="">{planId === "" ? "先選方案" : "請選擇"}</option>
          {options.data?.sum_insured.map((n) => (
            <option key={n} value={n}>
              {n.toLocaleString()} 元
            </option>
          ))}
        </select>
      </label>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="block text-sm font-medium">保險開始日（選填）</span>
          <input
            type="date"
            name="start_date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={`${input} w-full`}
          />
        </label>
        <label className="block space-y-1">
          <span className="block text-sm font-medium">保險結束日（選填）</span>
          <input
            type="date"
            name="end_date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className={`${input} w-full`}
          />
        </label>
      </div>
      <p className="text-xs text-gray-500">
        這是依你的選擇建立的保單，沒有經過保單文件驗證，加購的保障也不會列入。
      </p>
      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={busy}
          className={primary}
          data-testid="create-manual-policy"
        >
          建立保單
        </Button>
        <Button type="button" onClick={onCancel} className={secondary}>
          取消
        </Button>
      </div>
    </form>
  );
}
