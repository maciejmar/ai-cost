"use client";

import { Lock, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/stat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { api, type Overview } from "@/lib/api";
import { PROVIDER_LABEL } from "@/lib/format";

type Credential = { provider_name: string; key_hint: string; created_at: string };

const WINDOW_PRESETS = [
  { label: "1 godzina", seconds: 3600 },
  { label: "3 godziny", seconds: 10800 },
  { label: "5 godzin", seconds: 18000 },
  { label: "24 godziny", seconds: 86400 },
  { label: "7 dni", seconds: 604800 },
];

export default function ProvidersPage() {
  const [creds, setCreds] = useState<Credential[]>([]);
  const [windows, setWindows] = useState<Overview["windows"]>([]);

  const load = useCallback(async () => {
    setCreds(await api<Credential[]>("/api/credentials"));
    setWindows((await api<Overview>("/api/stats/overview")).windows);
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Providerzy i limity"
        description="Klucze upstream są szyfrowane w bazie (Fernet). Okno subskrypcji to własny limit tokenów, np. 1M na 3 godziny."
      />
      <div className="grid gap-3 lg:grid-cols-2">
        {(["anthropic", "openai"] as const).map((p) => (
          <ProviderSettings
            key={p}
            provider={p}
            credential={creds.find((c) => c.provider_name === p)}
            window={windows.find((w) => w.provider === p)}
            onChange={load}
          />
        ))}
        <ProviderSettings provider="litellm" window={windows.find((w) => w.provider === "litellm")} onChange={load} />
      </div>
    </>
  );
}

function ProviderSettings({
  provider,
  credential,
  window: w,
  onChange,
}: {
  provider: "anthropic" | "openai" | "litellm";
  credential?: Credential;
  window?: Overview["windows"][number];
  onChange: () => void;
}) {
  const [key, setKey] = useState("");
  const [limit, setLimit] = useState<string>("");
  const [seconds, setSeconds] = useState<number>(10800);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    setLimit(w?.subscription.token_limit?.toString() ?? "");
    if (w?.subscription.window_seconds) setSeconds(w.subscription.window_seconds);
  }, [w]);

  async function saveKey(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/credentials/${provider}`, { method: "PUT", json: { api_key: key } });
      setKey("");
      setMsg("Klucz zapisany.");
      onChange();
    } catch (err) {
      setMsg((err as Error).message);
    }
  }

  async function removeKey() {
    if (!confirm(`Usunąć klucz ${PROVIDER_LABEL[provider]}?`)) return;
    await api(`/api/credentials/${provider}`, { method: "DELETE" });
    onChange();
  }

  async function saveWindow(e: React.FormEvent) {
    e.preventDefault();
    await api(`/api/windows/${provider}`, {
      method: "PUT",
      json: { token_limit: limit ? Number(limit) : null, window_seconds: limit ? seconds : null },
    });
    setMsg("Okno zapisane.");
    onChange();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {PROVIDER_LABEL[provider]}
          {provider === "litellm" ? (
            <Badge>klucz z konfiguracji serwera</Badge>
          ) : credential ? (
            <Badge tone="good">
              <Lock className="h-3 w-3" /> {credential.key_hint}
            </Badge>
          ) : (
            <Badge tone="warning">brak klucza</Badge>
          )}
        </CardTitle>
        <CardDescription>
          {provider === "litellm"
            ? "Lokalne modele Ollama przez istniejący LiteLLM na serwerze GPU — ostatni fallback w tierach cheap."
            : "Bez klucza ten provider jest pomijany w routingu (fallback idzie do następnego)."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {provider !== "litellm" && (
          <form onSubmit={saveKey} className="flex items-end gap-2">
            <div className="flex-1">
              <Field label={credential ? "Zastąp klucz API" : "Klucz API"}>
                <Input
                  type="password"
                  autoComplete="off"
                  required
                  minLength={10}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder={provider === "anthropic" ? "sk-ant-…" : "sk-…"}
                />
              </Field>
            </div>
            <Button type="submit">Zapisz</Button>
            {credential && (
              <Button type="button" variant="ghost" size="icon" aria-label="Usuń klucz" onClick={removeKey}>
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </form>
        )}
        <form onSubmit={saveWindow} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
          <Field label="Limit tokenów w oknie" hint="Puste = wyłączone">
            <Input type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="1000000" />
          </Field>
          <Field label="Długość okna">
            <Select value={seconds} onChange={(e) => setSeconds(Number(e.target.value))}>
              {WINDOW_PRESETS.map((p) => (
                <option key={p.seconds} value={p.seconds}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit" variant="outline">
            Ustaw okno
          </Button>
        </form>
        {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
      </CardContent>
    </Card>
  );
}
