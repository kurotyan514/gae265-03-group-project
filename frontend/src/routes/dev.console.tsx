import { Button } from "@base-ui/react/button";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

export const Route = createFileRoute("/dev/console")({
  component: ConsolePage,
});

// 操作清單、參數與範例都在執行時讀自後端的 /api/v1/openapi.json，後端改了這裡不用跟著改
interface Param {
  name: string;
  in: "path" | "query";
  required?: boolean;
  schema?: { default?: unknown; examples?: unknown[] };
  examples?: Record<string, { summary?: string; value: unknown }>;
}
interface Operation {
  id: string;
  method: string;
  path: string;
  summary: string;
  params: Param[];
  bodyExamples: Record<string, { summary?: string; value: unknown }> | null;
}
interface Spec {
  paths: Record<
    string,
    Record<
      string,
      {
        operationId: string;
        summary?: string;
        parameters?: Param[];
        requestBody?: {
          content?: {
            "application/json"?: { examples?: Operation["bodyExamples"] };
          };
        };
      }
    >
  >;
}

function operationsOf(spec: Spec): Operation[] {
  return Object.entries(spec.paths).flatMap(([path, methods]) =>
    Object.entries(methods).map(([method, op]) => ({
      id: op.operationId,
      method: method.toUpperCase(),
      path,
      summary: op.summary ?? op.operationId,
      params: op.parameters ?? [],
      bodyExamples: op.requestBody?.content?.["application/json"]?.examples ?? null,
    })),
  );
}

function firstValue(param: Param): string {
  const example = param.examples ? Object.values(param.examples)[0]?.value : undefined;
  const value = example ?? param.schema?.examples?.[0] ?? param.schema?.default;
  return value === undefined || value === null ? "" : String(value);
}

function initialValues(op: Operation): Record<string, string> {
  return Object.fromEntries(op.params.map((p) => [p.name, firstValue(p)]));
}

function initialBody(op: Operation): string {
  const first = op.bodyExamples ? Object.values(op.bodyExamples)[0] : undefined;
  return first ? JSON.stringify(first.value, null, 2) : "";
}

interface Result {
  status: number;
  ms: number;
  body: string;
}

function buildUrl(op: Operation, values: Record<string, string>): string {
  let url = op.path;
  const query = new URLSearchParams();
  for (const p of op.params) {
    const value = values[p.name] ?? "";
    if (p.in === "path") url = url.replace(`{${p.name}}`, encodeURIComponent(value));
    else if (value !== "") query.set(p.name, value);
  }
  const qs = query.toString();
  return qs ? `${url}?${qs}` : url;
}

function curlOf(op: Operation, url: string, body: string): string {
  const base = `curl -s -X ${op.method} '${window.location.origin}${url}'`;
  if (!body) return base;
  return `${base} -H 'content-type: application/json' -d '${body.replace(/\s*\n\s*/g, " ")}'`;
}

function ConsolePage() {
  const spec = useQuery({
    queryKey: ["dev-openapi"],
    queryFn: async (): Promise<Spec> => {
      const response = await fetch("/api/v1/openapi.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
  });
  if (spec.error) {
    return (
      <p role="alert" className="text-red-600">
        無法讀取後端的 OpenAPI：{spec.error.message}
      </p>
    );
  }
  if (!spec.data) return <p>讀取中…</p>;
  return <Console operations={operationsOf(spec.data)} />;
}

function Console({ operations }: { operations: Operation[] }) {
  const [opId, setOpId] = useState(operations[0]?.id ?? "");
  const op = operations.find((o) => o.id === opId);
  const [values, setValues] = useState<Record<string, string>>(() => (op ? initialValues(op) : {}));
  const [body, setBody] = useState(() => (op ? initialBody(op) : ""));
  const [result, setResult] = useState<Result | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!op) return <p role="alert">OpenAPI 裡沒有任何 API。</p>;

  const url = buildUrl(op, values);
  const hasBody = op.method !== "GET";

  function select(id: string) {
    const next = operations.find((o) => o.id === id);
    if (!next) return;
    setOpId(id);
    setValues(initialValues(next));
    setBody(initialBody(next));
    setResult(null);
    setError(null);
  }

  async function send(current: Operation) {
    setSending(true);
    setError(null);
    const started = performance.now();
    try {
      const response = await fetch(url, {
        method: current.method,
        headers: hasBody ? { "content-type": "application/json" } : undefined,
        body: hasBody ? body : undefined,
      });
      const text = await response.text();
      let pretty = text;
      try {
        pretty = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        // 不是 JSON 就原樣顯示
      }
      setResult({
        status: response.status,
        ms: Math.round(performance.now() - started),
        body: pretty,
      });
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="space-y-4">
      <label className="block space-y-1">
        <span className="font-medium">API</span>
        <select
          value={opId}
          onChange={(e) => select(e.target.value)}
          className="w-full rounded-md border px-2 py-1"
          data-testid="operation"
        >
          {operations.map((o) => (
            <option key={o.id} value={o.id}>
              {o.method} {o.path}（{o.id}）
            </option>
          ))}
        </select>
      </label>

      {op.params.length > 0 && (
        <fieldset className="space-y-2 rounded-md border p-3">
          <legend className="px-1 font-medium">參數</legend>
          {op.params.map((p) => (
            <label key={p.name} className="grid grid-cols-[8rem_1fr] items-center gap-2">
              <span>
                {p.name}
                <span className="ml-1 text-xs text-gray-500">{p.in}</span>
              </span>
              <input
                value={values[p.name] ?? ""}
                onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                className="rounded-md border px-2 py-1"
                list={p.examples ? `ex-${p.name}` : undefined}
              />
              {p.examples && (
                <datalist id={`ex-${p.name}`}>
                  {Object.values(p.examples).map((ex) => (
                    <option key={String(ex.value)} value={String(ex.value)}>
                      {ex.summary}
                    </option>
                  ))}
                </datalist>
              )}
            </label>
          ))}
        </fieldset>
      )}

      {hasBody && (
        <div className="space-y-2">
          {op.bodyExamples && (
            <label className="block space-y-1">
              <span className="font-medium">範例</span>
              <select
                defaultValue=""
                onChange={(e) => {
                  const picked = op.bodyExamples?.[e.target.value];
                  if (picked) setBody(JSON.stringify(picked.value, null, 2));
                }}
                className="w-full rounded-md border px-2 py-1"
                data-testid="example"
              >
                <option value="" disabled>
                  選一個範例帶入
                </option>
                {Object.entries(op.bodyExamples).map(([key, ex]) => (
                  <option key={key} value={key}>
                    {ex.summary ?? key}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block space-y-1">
            <span className="font-medium">Request body（JSON，可以自己改）</span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={10}
              spellCheck={false}
              className="w-full rounded-md border p-2 font-mono text-sm"
              data-testid="body"
            />
          </label>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button
          onClick={() => void send(op)}
          disabled={sending}
          className="rounded-md bg-gray-900 px-4 py-1 text-white hover:bg-gray-700 data-[disabled]:opacity-50"
        >
          {sending ? "送出中…" : "送出"}
        </Button>
        <code className="truncate text-sm text-gray-600">
          {op.method} {url}
        </code>
        <Button
          onClick={() => void navigator.clipboard.writeText(curlOf(op, url, hasBody ? body : ""))}
          className="ml-auto rounded-md border px-3 py-1 text-sm hover:bg-gray-100"
        >
          複製 curl
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-red-600">
          連不到後端：{error}
        </p>
      )}
      {result && (
        <div className="space-y-1">
          <p>
            <span
              data-testid="status"
              className={
                result.status < 300 ? "font-bold text-green-700" : "font-bold text-red-600"
              }
            >
              {result.status}
            </span>
            <span className="ml-2 text-sm text-gray-600">{result.ms} ms</span>
          </p>
          <pre
            data-testid="response"
            className="max-h-[32rem] overflow-auto rounded-md bg-gray-100 p-3 text-sm"
          >
            {result.body}
          </pre>
        </div>
      )}
    </section>
  );
}
