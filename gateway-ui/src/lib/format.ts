export type Currency = "USD" | "PLN";

export function money(usd: number, currency: Currency, rate: number, precise = false) {
  const value = currency === "PLN" ? usd * rate : usd;
  const digits = precise || Math.abs(value) < 1 ? 4 : 2;
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Etykiety osi: okrągłe wartości, bez zbędnych miejsc po przecinku. */
export function moneyTick(value: number, currency: Currency) {
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency,
    maximumFractionDigits: value !== 0 && Math.abs(value) < 10 ? 2 : 0,
  }).format(value);
}

export function compact(n: number) {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function int(n: number) {
  return new Intl.NumberFormat("pl-PL").format(n);
}

export function duration(seconds: number) {
  if (seconds <= 0) return "0s";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

export const PROVIDER_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  litellm: "Lokalne (LiteLLM)",
};
