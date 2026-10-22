"use client";

import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/stat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/input";
import { api } from "@/lib/api";

type Routing = {
  strategies: Record<string, string[]>;
  models: Record<string, { provider: string; equivalents: string[] }>;
  auto: { smart_threshold: number; balanced_threshold: number };
};

type Preview = {
  strategy: string;
  complexity: number | null;
  reasons: string[];
  candidates: { model: string; provider: string }[];
};

export default function RoutingPage() {
  const [routing, setRouting] = useState<Routing | null>(null);
  const [prompt, setPrompt] = useState("Przeanalizuj architekturę tego serwisu krok po kroku i zaproponuj plan migracji.");
  const [strategy, setStrategy] = useState("auto");
  const [preview, setPreview] = useState<Preview | null>(null);

  useEffect(() => {
    api<Routing>("/api/routing").then(setRouting);
  }, []);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setPreview(await api<Preview>("/api/routing/preview", { method: "POST", json: { prompt, strategy } }));
  }

  return (
    <>
      <PageHeader
        title="Routing"
        description="Tiery modeli z gateway/routing.yml. Kolejni kandydaci to fallback przy 429, 5xx lub wyczerpanym oknie."
      />

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Strategie</CardTitle>
            <CardDescription>
              auto: złożoność ≥ {routing?.auto.smart_threshold} → smart, ≥ {routing?.auto.balanced_threshold} → balanced, inaczej cheap
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {routing &&
              Object.entries(routing.strategies).map(([name, chain]) => (
                <div key={name} className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="primary" className="w-16 justify-center">
                    {name}
                  </Badge>
                  {chain.map((m, i) => (
                    <span key={m} className="flex items-center gap-1.5 text-sm">
                      {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                      {m}
                      <span className="text-xs text-muted-foreground">{routing.models[m]?.provider}</span>
                    </span>
                  ))}
                </div>
              ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Podgląd decyzji</CardTitle>
            <CardDescription>Sprawdź, gdzie trafi prompt — bez wywoływania modelu.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={run} className="flex flex-col gap-3">
              <textarea
                className="min-h-24 w-full rounded-md border border-border bg-surface p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
              <div className="flex items-end gap-2">
                <Field label="X-Gateway-Strategy">
                  <Select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                    {["auto", "cheap", "smart", "fast"].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </Select>
                </Field>
                <Button type="submit">Sprawdź</Button>
              </div>
            </form>
            {preview && (
              <div className="mt-4 flex flex-col gap-2 text-sm">
                <div>
                  Tier: <span className="font-semibold">{preview.strategy}</span>
                  {preview.complexity != null && <span className="text-muted-foreground"> · złożoność {preview.complexity}</span>}
                </div>
                {preview.reasons.length > 0 && (
                  <ul className="list-inside list-disc text-xs text-muted-foreground">
                    {preview.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                )}
                <div className="flex flex-wrap items-center gap-1.5">
                  {preview.candidates.map((c, i) => (
                    <span key={c.model} className="flex items-center gap-1.5">
                      {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                      <Badge tone={i === 0 ? "good" : "neutral"}>{c.model}</Badge>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
