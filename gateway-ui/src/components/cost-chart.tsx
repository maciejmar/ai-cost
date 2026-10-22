"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money, moneyTick, type Currency } from "@/lib/format";
import type { CostRow } from "@/lib/api";

const MAX_SERIES = 7; // 8. slot = "Inne" — nigdy nie generujemy dodatkowych odcieni
const OTHER = "Inne";

/** Kolor podąża za aplikacją (kolejność alfabetyczna), nie za rankingiem wydatków. */
export function seriesFor(apps: string[]) {
  const sorted = [...apps].sort((a, b) => a.localeCompare(b));
  const keep = sorted.length > MAX_SERIES + 1 ? sorted.slice(0, MAX_SERIES) : sorted;
  const colors = new Map(keep.map((a, i) => [a, `var(--series-${i + 1})`]));
  if (keep.length < sorted.length) colors.set(OTHER, `var(--series-${MAX_SERIES + 1})`);
  return colors;
}

export function pivot(rows: CostRow[], colors: Map<string, string>, currency: Currency, rate: number) {
  const factor = currency === "PLN" ? rate : 1;
  const buckets = new Map<string, Record<string, number | string>>();
  for (const r of rows) {
    const key = colors.has(r.app_name) ? r.app_name : OTHER;
    const b = buckets.get(r.bucket) ?? { bucket: r.bucket };
    b[key] = ((b[key] as number) ?? 0) + r.cost_usd * factor;
    buckets.set(r.bucket, b);
  }
  return [...buckets.values()].sort((a, b) => String(a.bucket).localeCompare(String(b.bucket)));
}

export function CostChart({ rows, currency, rate }: { rows: CostRow[]; currency: Currency; rate: number }) {
  const colors = seriesFor([...new Set(rows.map((r) => r.app_name))]);
  const series = [...colors.keys()];
  const data = pivot(rows, colors, currency, rate);
  const fmt = (v: number) => money(currency === "PLN" ? v / rate : v, currency, rate);

  if (!rows.length) {
    return <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">Brak wywołań w tym okresie.</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      {series.length > 1 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {series.map((s) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: colors.get(s) }} />
              {s}
            </span>
          ))}
        </div>
      )}
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
            <XAxis
              dataKey="bucket"
              tickLine={false}
              axisLine={{ stroke: "var(--viz-grid)" }}
              tick={{ fill: "var(--viz-axis)", fontSize: 11 }}
              tickFormatter={(v: string) => v.slice(5)}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={72}
              tick={{ fill: "var(--viz-axis)", fontSize: 11 }}
              tickFormatter={(v: number) => moneyTick(v, currency)}
            />
            <Tooltip
              cursor={{ fill: "var(--viz-grid)", opacity: 0.4 }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const total = payload.reduce((s, p) => s + Number(p.value ?? 0), 0);
                return (
                  <div className="min-w-44 rounded-md border border-border bg-surface p-2 text-xs shadow-sm">
                    <div className="mb-1 font-medium">{label}</div>
                    {[...payload].reverse().map((p) => (
                      <div key={String(p.dataKey)} className="flex items-center justify-between gap-4">
                        <span className="flex items-center gap-1.5 text-muted-foreground">
                          <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
                          {String(p.dataKey)}
                        </span>
                        <span className="tabular">{fmt(Number(p.value))}</span>
                      </div>
                    ))}
                    <div className="mt-1 flex justify-between border-t border-border pt-1 font-medium">
                      <span>Razem</span>
                      <span className="tabular">{fmt(total)}</span>
                    </div>
                  </div>
                );
              }}
            />
            {series.map((s, i) => (
              <Bar
                key={s}
                dataKey={s}
                stackId="cost"
                fill={colors.get(s)}
                stroke="var(--viz-surface)"
                strokeWidth={2}
                maxBarSize={24}
                radius={i === series.length - 1 ? [4, 4, 0, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
