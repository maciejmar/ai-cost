"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/components/session";
import { PageHeader, Stat } from "@/components/stat";
import { TokenRing } from "@/components/token-ring";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { api, type Overview, type Window } from "@/lib/api";
import { compact, duration, int, money, PROVIDER_LABEL } from "@/lib/format";

export default function OverviewPage() {
  const { currency, rate, setRate } = useSession();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api<Overview>("/api/stats/overview")
        .then((d) => {
          setData(d);
          setRate(d.usd_pln);
          setError(null);
        })
        .catch((e) => setError(e.message));
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [setRate]);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Ładowanie…</p>;

  const visible = data.windows.filter(
    (w) => w.provider !== "litellm" || w.subscription.token_limit || w.subscription.used,
  );

  return (
    <>
      <PageHeader title="Przegląd" description="Okna limitów tokenów i bieżące wydatki. Odświeżane co 10 s." />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Koszt dziś" value={money(data.today.cost_usd, currency, rate)} sub={`${int(data.today.requests)} zapytań`} />
        <Stat label="Koszt w tym miesiącu" value={money(data.month.cost_usd, currency, rate)} sub={`${int(data.month.requests)} zapytań`} />
        <Stat label="Tokeny dziś" value={compact(data.today.tokens)} />
        <Stat label="Tokeny w tym miesiącu" value={compact(data.month.tokens)} />
      </div>

      <div className="mb-6 grid gap-3 lg:grid-cols-2">
        {visible.map((w) => (
          <ProviderCard key={w.provider} w={w} />
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ostatnie zapytania</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">Jeszcze brak ruchu. Utwórz aplikację i klucz w zakładce „Aplikacje i klucze”.</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Czas</Th>
                  <Th>Aplikacja</Th>
                  <Th>Model</Th>
                  <Th>Strategia</Th>
                  <Th className="text-right">Wejście / wyjście</Th>
                  <Th className="text-right">Koszt</Th>
                  <Th className="text-right">Czas</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((r, i) => (
                  <tr key={i}>
                    <Td className="tabular text-muted-foreground">{when(r.timestamp)}</Td>
                    <Td>{r.app_name}</Td>
                    <Td>
                      {r.model_used}
                      {r.fallback_count > 0 && (
                        <Badge tone="warning" className="ml-2">
                          fallback ×{r.fallback_count}
                        </Badge>
                      )}
                    </Td>
                    <Td className="text-muted-foreground">{r.strategy}</Td>
                    <Td className="tabular text-right">
                      {int(r.input_tokens + r.cached_tokens)} / {int(r.output_tokens)}
                    </Td>
                    <Td className="tabular text-right">{money(r.calculated_cost, currency, rate, true)}</Td>
                    <Td className="tabular text-right text-muted-foreground">{duration(r.latency_ms / 1000)}</Td>
                    <Td>
                      <Badge tone={r.status === "success" ? "good" : "critical"}>{r.status === "success" ? "✓ ok" : "✕ błąd"}</Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function when(ts: string) {
  const d = new Date(ts);
  const time = d.toLocaleTimeString("pl-PL");
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString("pl-PL")} ${time}`;
}

function ProviderCard({ w }: { w: Window }) {
  const sub = w.subscription;
  const up = w.upstream;
  const upstreamUsed = up.tokens_limit != null && up.tokens_remaining != null ? up.tokens_limit - up.tokens_remaining : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{PROVIDER_LABEL[w.provider] ?? w.provider}</CardTitle>
        <CardDescription>
          {up.requests_limit != null
            ? `Zapytania: ${int(up.requests_remaining ?? 0)} / ${int(up.requests_limit)} pozostało`
            : "Limity API pojawią się po pierwszym zapytaniu."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-4">
        <TokenRing
          title={sub.window_seconds ? `Okno subskrypcji (${duration(sub.window_seconds)})` : "Okno subskrypcji"}
          used={sub.used}
          limit={sub.token_limit}
          resetAt={sub.resets_at}
          emptyHint="Ustaw limit w „Providerzy i limity”"
        />
        <TokenRing
          title="Limit tokenów API"
          used={upstreamUsed}
          limit={up.tokens_limit}
          resetAt={up.tokens_reset_at}
          emptyHint="Brak nagłówków od providera"
        />
      </CardContent>
    </Card>
  );
}
