"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/api/auth/${mode}`, { method: "POST", json: { email, password } });
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-base">AIGateway-X</CardTitle>
          <CardDescription>
            {mode === "login" ? "Zaloguj się do panelu bramki." : "Pierwsze konto zostaje administratorem."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <Field label="E-mail">
              <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Hasło" hint={mode === "register" ? "Minimum 10 znaków" : undefined}>
              <Input
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button type="submit" disabled={busy}>
              {mode === "login" ? "Zaloguj" : "Utwórz konto"}
            </Button>
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setMode(mode === "login" ? "register" : "login")}
            >
              {mode === "login" ? "Nie masz konta? Zarejestruj się" : "Masz już konto? Zaloguj się"}
            </button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
