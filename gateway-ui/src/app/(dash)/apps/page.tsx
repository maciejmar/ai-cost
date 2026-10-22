"use client";

import { Copy, KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/stat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { api, type App } from "@/lib/api";
import { compact, int } from "@/lib/format";

type Form = Omit<App, "id" | "usage" | "keys">;

const EMPTY: Form = {
  app_name: "",
  token_budget_limit: null,
  soft_limit_pct: 80,
  budget_period: "month",
  tpm_limit: null,
  default_strategy: "auto",
  active: true,
};

const PERIOD_LABEL = { day: "dzień", week: "tydzień", month: "miesiąc" };

export default function AppsPage() {
  const [apps, setApps] = useState<App[]>([]);
  const [editing, setEditing] = useState<{ id: string | null; form: Form } | null>(null);
  const [newKey, setNewKey] = useState<{ app: string; key: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => api<App[]>("/api/apps").then(setApps), []);
  useEffect(() => {
    load();
  }, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    try {
      if (editing.id) await api(`/api/apps/${editing.id}`, { method: "PUT", json: editing.form });
      else await api("/api/apps", { method: "POST", json: editing.form });
      setEditing(null);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function createKey(app: App) {
    const res = await api<{ key: string }>(`/api/apps/${app.id}/keys`, { method: "POST" });
    setNewKey({ app: app.app_name, key: res.key });
    load();
  }

  async function revokeKey(app: App, keyId: string) {
    if (!confirm("Unieważnić klucz? Agenci używający go przestaną działać.")) return;
    await api(`/api/apps/${app.id}/keys/${keyId}`, { method: "DELETE" });
    load();
  }

  async function remove(app: App) {
    if (!confirm(`Usunąć aplikację ${app.app_name} wraz z kluczami i historią kosztów?`)) return;
    await api(`/api/apps/${app.id}`, { method: "DELETE" });
    load();
  }

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setEditing((e) => e && { ...e, form: { ...e.form, [k]: v } });
  const num = (v: string) => (v === "" ? null : Number(v));

  return (
    <>
      <PageHeader
        title="Aplikacje i klucze"
        description="Każdy agent dostaje własną aplikację, klucz agx_… i limity tokenów."
        actions={
          <Button onClick={() => setEditing({ id: null, form: EMPTY })}>
            <Plus className="h-4 w-4" /> Nowa aplikacja
          </Button>
        }
      />

      {newKey && (
        <Card className="mb-6 border-primary/40">
          <CardHeader>
            <CardTitle>Nowy klucz dla {newKey.app}</CardTitle>
            <CardDescription>Skopiuj go teraz — nie zostanie pokazany ponownie.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex gap-2">
              <Input readOnly value={newKey.key} className="font-mono text-xs" />
              <Button variant="outline" onClick={() => navigator.clipboard.writeText(newKey.key)}>
                <Copy className="h-4 w-4" /> Kopiuj
              </Button>
            </div>
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{`from openai import OpenAI

client = OpenAI(
    base_url="${typeof window !== "undefined" ? window.location.origin : ""}/v1",
    api_key="${newKey.key}",
    default_headers={"X-App-ID": "${newKey.app}"},
)
client.chat.completions.create(
    model="auto",                                   # albo konkretny model z katalogu
    messages=[{"role": "user", "content": "..."}],
    extra_headers={"X-Gateway-Strategy": "cheap"},  # cheap | smart | fast | auto
)`}</pre>
            <Button variant="ghost" size="sm" className="self-start" onClick={() => setNewKey(null)}>
              Zamknij
            </Button>
          </CardContent>
        </Card>
      )}

      {editing && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>{editing.id ? "Edytuj aplikację" : "Nowa aplikacja"}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={save} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Nazwa (X-App-ID)" hint="Litery, cyfry, . _ -">
                <Input required value={editing.form.app_name} onChange={(e) => set("app_name", e.target.value)} placeholder="Content-Agent-01" />
              </Field>
              <Field label="Domyślna strategia" hint="Gdy agent nie wyśle X-Gateway-Strategy">
                <Select value={editing.form.default_strategy} onChange={(e) => set("default_strategy", e.target.value as Form["default_strategy"])}>
                  <option value="auto">auto (ocena złożoności)</option>
                  <option value="cheap">cheap</option>
                  <option value="smart">smart</option>
                  <option value="fast">fast</option>
                </Select>
              </Field>
              <Field label="Twardy limit tokenów" hint="Puste = bez limitu">
                <Input type="number" min={1} value={editing.form.token_budget_limit ?? ""} onChange={(e) => set("token_budget_limit", num(e.target.value))} />
              </Field>
              <Field label="Okres limitu">
                <Select value={editing.form.budget_period} onChange={(e) => set("budget_period", e.target.value as Form["budget_period"])}>
                  <option value="day">dzień</option>
                  <option value="week">tydzień</option>
                  <option value="month">miesiąc</option>
                </Select>
              </Field>
              <Field label="Miękki próg (%)" hint="Po przekroczeniu → tańszy tier">
                <Input type="number" min={1} max={100} value={editing.form.soft_limit_pct} onChange={(e) => set("soft_limit_pct", Number(e.target.value))} />
              </Field>
              <Field label="Limit TPM" hint="Tokeny / minutę, puste = brak">
                <Input type="number" min={1} value={editing.form.tpm_limit ?? ""} onChange={(e) => set("tpm_limit", num(e.target.value))} />
              </Field>
              <Field label="Status">
                <Select value={editing.form.active ? "1" : "0"} onChange={(e) => set("active", e.target.value === "1")}>
                  <option value="1">aktywna</option>
                  <option value="0">wyłączona</option>
                </Select>
              </Field>
              <div className="flex items-end gap-2">
                <Button type="submit">Zapisz</Button>
                <Button type="button" variant="ghost" onClick={() => setEditing(null)}>
                  Anuluj
                </Button>
              </div>
              {error && <p className="text-xs text-destructive sm:col-span-4">{error}</p>}
            </form>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3">
        {apps.length === 0 && <p className="text-sm text-muted-foreground">Brak aplikacji. Utwórz pierwszą, aby wygenerować klucz.</p>}
        {apps.map((app) => {
          const u = app.usage!;
          const pct = u.limit ? Math.min(u.used / u.limit, 1) : null;
          const tone = pct == null ? "var(--series-1)" : pct >= 1 ? "var(--viz-status-critical)" : u.soft_limit && u.used >= u.soft_limit ? "var(--viz-status-warning)" : "var(--series-1)";
          return (
            <Card key={app.id}>
              <CardHeader className="flex-row items-start justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <CardTitle className="flex items-center gap-2">
                    {app.app_name}
                    {!app.active && <Badge>wyłączona</Badge>}
                    <Badge tone="primary">{app.default_strategy}</Badge>
                  </CardTitle>
                  <CardDescription>
                    {u.limit
                      ? `${int(u.used)} / ${int(u.limit)} tokenów w tym okresie (${PERIOD_LABEL[app.budget_period]})`
                      : `${int(u.used)} tokenów w tym okresie (${PERIOD_LABEL[app.budget_period]}) · bez limitu`}
                    {app.tpm_limit ? ` · TPM ${compact(u.tpm_used)} / ${compact(app.tpm_limit)}` : ""}
                  </CardDescription>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" onClick={() => createKey(app)}>
                    <KeyRound className="h-3.5 w-3.5" /> Nowy klucz
                  </Button>
                  <Button size="icon" variant="ghost" aria-label="Edytuj" onClick={() => setEditing({ id: app.id, form: { ...app } })}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="icon" variant="ghost" aria-label="Usuń" onClick={() => remove(app)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {pct != null && (
                  <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--viz-track)" }}>
                    <div className="h-full rounded-full" style={{ width: `${pct * 100}%`, background: tone }} />
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {app.keys?.length === 0 && <span className="text-xs text-muted-foreground">Brak kluczy.</span>}
                  {app.keys?.map((k) => (
                    <span key={k.id} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 font-mono text-xs">
                      {k.prefix}…
                      {k.revoked ? (
                        <Badge tone="critical">unieważniony</Badge>
                      ) : (
                        <>
                          <span className="font-sans text-muted-foreground">
                            {k.last_used_at ? `użyty ${new Date(k.last_used_at).toLocaleString("pl-PL")}` : "nieużywany"}
                          </span>
                          <button className="text-muted-foreground hover:text-destructive" aria-label="Unieważnij" onClick={() => revokeKey(app, k.id)}>
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </>
                      )}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </>
  );
}
