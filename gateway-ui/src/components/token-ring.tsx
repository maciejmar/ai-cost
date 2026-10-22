"use client";

import { AlertTriangle, Clock } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { useNow } from "@/components/session";
import { compact, duration, int } from "@/lib/format";

type Props = {
  title: string;
  used: number | null;
  limit: number | null;
  resetAt: string | null;
  emptyHint: string;
};

/** Pierścień "zużyte vs pozostałe" w bieżącym oknie + odliczanie do resetu. */
export function TokenRing({ title, used, limit, resetAt, emptyHint }: Props) {
  const now = useNow();
  const known = limit != null && limit > 0 && used != null;
  const usedClamped = known ? Math.min(used!, limit!) : 0;
  const pct = known ? usedClamped / limit! : 0;
  const secondsLeft = resetAt ? Math.max((new Date(resetAt).getTime() - now) / 1000, 0) : null;

  // Stan (nie tożsamość serii) → kolory statusu, zawsze z ikoną i etykietą
  const state = pct >= 0.9 ? "critical" : pct >= 0.75 ? "warning" : "normal";
  const usedColor =
    state === "critical" ? "var(--viz-status-critical)" : state === "warning" ? "var(--viz-status-warning)" : "var(--series-1)";

  const data = known
    ? [
        { name: "Zużyte", value: usedClamped, color: usedColor },
        { name: "Pozostało", value: limit! - usedClamped, color: "var(--viz-track)" },
      ]
    : [{ name: "Brak danych", value: 1, color: "var(--viz-track)" }];

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <div className="relative h-36 w-36">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              innerRadius="74%"
              outerRadius="100%"
              startAngle={90}
              endAngle={-270}
              stroke="var(--viz-surface)"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Pie>
            {known && (
              <Tooltip
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm">
                      {payload[0].name}: <span className="tabular font-medium">{int(payload[0].value as number)}</span>
                    </div>
                  ) : null
                }
              />
            )}
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          {known ? (
            <>
              <span className="text-2xl font-semibold">{Math.round(pct * 100)}%</span>
              <span className="text-[11px] text-muted-foreground">
                {compact(usedClamped)} / {compact(limit!)}
              </span>
            </>
          ) : (
            <span className="px-6 text-center text-[11px] text-muted-foreground">{emptyHint}</span>
          )}
        </div>
      </div>
      {state !== "normal" && known && (
        <span className={state === "critical" ? "flex items-center gap-1 text-[11px] text-destructive" : "flex items-center gap-1 text-[11px] text-warning"}>
          <AlertTriangle className="h-3 w-3" />
          {state === "critical" ? "Prawie wyczerpane" : "Wysokie zużycie"}
        </span>
      )}
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <Clock className="h-3 w-3" />
        {secondsLeft == null ? "brak resetu" : secondsLeft === 0 ? "okno odnowione" : (
          <>
            reset za <span className="tabular font-medium text-foreground">{duration(secondsLeft)}</span>
          </>
        )}
      </div>
    </div>
  );
}
