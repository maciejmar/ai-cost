// Cienki klient REST — sesja w ciasteczku httpOnly ustawianym przez bramkę

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { loc?: string[]; msg: string }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join(", ")
          : (data?.error?.message ?? res.statusText);
    throw new ApiError(res.status, message);
  }
  return data as T;
}

export type User = { id: string; email: string; role: "admin" | "user" };

export type Window = {
  provider: string;
  subscription: { token_limit: number | null; window_seconds: number | null; used: number; resets_at: string | null };
  upstream: {
    tokens_limit: number | null;
    tokens_remaining: number | null;
    tokens_reset_at: string | null;
    requests_limit: number | null;
    requests_remaining: number | null;
    requests_reset_at: string | null;
  };
};

export type Totals = { cost_usd: number; tokens: number; requests: number };

export type Overview = {
  usd_pln: number;
  today: Totals;
  month: Totals;
  windows: Window[];
  recent: {
    timestamp: string;
    app_name: string;
    provider_name: string;
    model_used: string;
    strategy: string;
    input_tokens: number;
    output_tokens: number;
    cached_tokens: number;
    calculated_cost: number;
    latency_ms: number;
    status: string;
    fallback_count: number;
  }[];
};

export type App = {
  id: string;
  app_name: string;
  token_budget_limit: number | null;
  soft_limit_pct: number;
  budget_period: "day" | "week" | "month";
  tpm_limit: number | null;
  default_strategy: "auto" | "cheap" | "smart" | "fast";
  active: boolean;
  usage?: { used: number; limit: number | null; soft_limit: number | null; resets_at: string; tpm_used: number };
  keys?: { id: string; prefix: string; revoked: boolean; last_used_at: string | null; created_at: string }[];
};

export type CostRow = { bucket: string; app_name: string; cost_usd: number; tokens: number; requests: number };
export type CostReport = {
  usd_pln: number;
  granularity: string;
  rows: CostRow[];
  by_model: {
    model: string;
    provider: string;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    cached_tokens: number;
    requests: number;
  }[];
};

export type Price = {
  model: string;
  provider_name: string;
  input_per_mtok: number;
  output_per_mtok: number;
  cached_input_per_mtok: number;
  cache_write_per_mtok: number;
  updated_at: string;
};
