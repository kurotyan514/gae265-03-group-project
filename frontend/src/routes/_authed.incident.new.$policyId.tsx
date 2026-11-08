import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { createIncident } from "../client";
import { ActionBar } from "../components/ui/ActionBar";
import { btn, btnPri } from "../components/ui/buttons";
import { Field, fieldInput } from "../components/ui/Field";
import { PageHead } from "../components/ui/PageHead";
import { box, errorText } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/incident/new/$policyId")({
  component: DescribePage,
});

/**
 * 2-2 描述事故（建立前）。這一版先沿用「說明發生了什麼事」的表單，換成設計稿的版型與樣式；
 * 對話畫面（固定第一句、選項 Chip、提問列）在 #217 做。
 */
function DescribePage() {
  const { policyId } = Route.useParams();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    // 目的地不再另外問：後端沒帶時用保單的目的地（#203）
    const res = await createIncident({
      path: { policy_id: policyId },
      body: { description: String(form.get("description")) },
    });
    setBusy(false);
    if (!res.data) return setError(errorText(res.error, res.response?.status));
    await navigate({ to: "/incident/$id", params: { id: res.data.incident.incident_id } });
  }

  return (
    <main className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead crumb="出事了：幫我處理理賠 · 描述事故" title="發生了什麼事？" />
      {error && (
        <p
          role="alert"
          className="m-0 rounded-btn bg-danger-soft px-4 py-2 t-caption-bold text-danger-ink"
          data-testid="error"
        >
          {error}
        </p>
      )}
      <form onSubmit={start} className={box} data-testid="start-form">
        <Field label="簡單說明" htmlFor="incident-description">
          <textarea
            id="incident-description"
            name="description"
            required
            rows={3}
            placeholder="例如：班機延誤了六小時"
            className={`${fieldInput} w-full`}
          />
        </Field>
        <ActionBar twoColumns>
          <Link to="/incident/new" search={{ policy: policyId }} className={btn}>
            上一步
          </Link>
          <ActionBar.Push>
            <ActionBar.Full>
              <button type="submit" disabled={busy} className={btnPri} data-testid="start">
                開始處理
              </button>
            </ActionBar.Full>
          </ActionBar.Push>
        </ActionBar>
      </form>
    </main>
  );
}
