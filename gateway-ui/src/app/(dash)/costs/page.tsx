"use client";

import { useEffect, useMemo, useState } from "react";
import { CostChart } from "@/components/cost-chart";
import { useSession } from "@/components/session";
import { PageHeader, Stat } from "@/components/stat";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { api, type CostReport } from "@/lib/api";
import { compact, int, money } from "@/lib/format";

const RANGES = [
  { label: "Ostatnie 7 dni", days: 7, granularity: "day" },
  { label: "Ostatnie 30 dni", days: 30, granularity: "day" },
  { label: "Ostatnie 12 tygodni", days: 84, granularity: "week" },
  { label: "Ostatnie 12 miesięcy", days: 365, granularity: "month" },
] as const;

export default function CostsPage() {
  const { currency, rate, setRate } = useSession();
  const [range, setRange] = useState(1);
  const [data, setData] = useState<CostReport | null>(null);

  useEffect(() => {
    const r = RANGES[range];
    api<CostReport>(`/api/stats/costs?granularity=${r.granularity}&days=${r.days}`).then((d) => {
      setData(d);
      setRate(d.usd_pln);
    });
  }, [range, setRate]);

  const perApp = useMemo(() => {
    const m = new Map<string, { cost: number; tokens: number; requests: number }>();
    for (const r of data?.rows ?? []) {
      const a = m.get(r.app_name) ?? { cost: 0, tokens: 0, requests: 0 };
      a.cost += r.cost_usd;
      a.tokens += r.tokens;
      a.requests += r.requests;
      m.set(r.app_name, a);
    }
    return [...m.entries()].sort((a, b) => b[1].cost - a[1].cost);
  }, [data]);

  const total = perApp.reduce((s, [, a]) => s + a.cost, 0);

  return (
    <>
      <PageHeader
        title="Koszty"
        description="Wydatki przypisane do aplikacji (nagłówek X-App-ID)."
        actions={
          <Select className="w-52" value={range} onChange={(e) => setRange(Number(e.target.value))}>
            {RANGES.map((r, i) => (
              <option key={r.label} value={i}>
                {r.label}
              </option>
            ))}
          </Select>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Razem w okresie" value={money(total, currency, rate)} />
        <Stat label="Aplikacje z ruchem" value={perApp.length} />
        <Stat label="Najdroższa aplikacja" value={perApp[0]?.[0] ?? "—"} sub={perApp[0] ? money(perApp[0][1].cost, currency, rate) : undefined} />
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Wydatki według aplikacji</CardTitle>
          <CardDescription>Skumulowane per {RANGES[range].granularity === "day" ? "dzień" : RANGES[range].granularity === "week" ? "tydzień" : "miesiąc"}</CardDescription>
        </CardHeader>
        <CardContent>{data ? <CostChart rows={data.rows} currency={currency} rate={rate} /> : <div className="h-72" />}</CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Aplikacje</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <thead>
                <tr>
                  <Th>Aplikacja</Th>
                  <Th className="text-right">Zapytania</Th>
                  <Th className="text-right">Tokeny</Th>
                  <Th className="text-right">Koszt</Th>
                  <Th className="text-right">Udział</Th>
                </tr>
              </thead>
              <tbody>
                {perApp.map(([name, a]) => (
                  <tr key={name}>
                    <Td>{name}</Td>
                    <Td className="tabular text-right">{int(a.requests)}</Td>
                    <Td className="tabular text-right">{compact(a.tokens)}</Td>
                    <Td className="tabular text-right">{money(a.cost, currency, rate)}</Td>
                    <Td className="tabular text-right text-muted-foreground">{total ? `${Math.round((a.cost / total) * 100)}%` : "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Modele</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <thead>
                <tr>
                  <Th>Model</Th>
                  <Th className="text-right">Wejście</Th>
                  <Th className="text-right">Cache</Th>
                  <Th className="text-right">Wyjście</Th>
                  <Th className="text-right">Koszt</Th>
                </tr>
              </thead>
              <tbody>
                {data?.by_model.map((m) => (
                  <tr key={m.model}>
                    <Td>
                      {m.model} <span className="text-xs text-muted-foreground">{m.provider}</span>
                    </Td>
                    <Td className="tabular text-right">{compact(m.input_tokens)}</Td>
                    <Td className="tabular text-right">{compact(m.cached_tokens)}</Td>
                    <Td className="tabular text-right">{compact(m.output_tokens)}</Td>
                    <Td className="tabular text-right">{money(m.cost_usd, currency, rate)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
