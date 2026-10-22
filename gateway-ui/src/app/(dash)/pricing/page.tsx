"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/session";
import { PageHeader } from "@/components/stat";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { api, type Price } from "@/lib/api";

const FIELDS = ["input_per_mtok", "output_per_mtok", "cached_input_per_mtok", "cache_write_per_mtok"] as const;
const LABELS = { input_per_mtok: "Wejście", output_per_mtok: "Wyjście", cached_input_per_mtok: "Odczyt cache", cache_write_per_mtok: "Zapis cache" };

export default function PricingPage() {
  const { user } = useSession();
  const isAdmin = user.role === "admin";
  const [prices, setPrices] = useState<Price[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Price>>({});
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(() => api<Price[]>("/api/pricing").then(setPrices), []);
  useEffect(() => {
    load();
  }, [load]);

  function edit(p: Price, field: (typeof FIELDS)[number], value: string) {
    setDrafts((d) => ({ ...d, [p.model]: { ...(d[p.model] ?? p), [field]: Number(value) } }));
  }

  async function save(model: string) {
    const p = drafts[model];
    try {
      await api(`/api/pricing/${encodeURIComponent(model)}`, { method: "PUT", json: p });
      setDrafts(({ [model]: _, ...rest }) => rest);
      setStatus(`Zapisano ${model}.`);
      load();
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Cennik"
        description={`USD za 1M tokenów. ${isAdmin ? "Zmiany obowiązują od kolejnego zapytania." : "Edycja wymaga roli admin."}`}
      />
      <Card>
        <CardContent className="pt-5">
          <Table>
            <thead>
              <tr>
                <Th>Model</Th>
                <Th>Provider</Th>
                {FIELDS.map((f) => (
                  <Th key={f} className="text-right">
                    {LABELS[f]}
                  </Th>
                ))}
                {isAdmin && <Th />}
              </tr>
            </thead>
            <tbody>
              {prices.map((p) => {
                const row = drafts[p.model] ?? p;
                return (
                  <tr key={p.model}>
                    <Td className="font-medium">{p.model}</Td>
                    <Td className="text-muted-foreground">{p.provider_name}</Td>
                    {FIELDS.map((f) => (
                      <Td key={f} className="text-right">
                        {isAdmin ? (
                          <Input
                            type="number"
                            step="0.001"
                            min={0}
                            className="tabular ml-auto h-8 w-24 text-right"
                            value={row[f]}
                            onChange={(e) => edit(p, f, e.target.value)}
                          />
                        ) : (
                          <span className="tabular">${row[f]}</span>
                        )}
                      </Td>
                    ))}
                    {isAdmin && (
                      <Td>
                        <Button size="sm" variant="outline" disabled={!drafts[p.model]} onClick={() => save(p.model)}>
                          Zapisz
                        </Button>
                      </Td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {status && <p className="mt-3 text-xs text-muted-foreground">{status}</p>}
        </CardContent>
      </Card>
    </>
  );
}
