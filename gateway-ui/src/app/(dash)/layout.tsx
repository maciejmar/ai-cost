"use client";

import { BarChart3, Boxes, Gauge, KeyRound, LogOut, Route, Tags } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { SessionProvider, useSession } from "@/components/session";
import { api, type User } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Przegląd", icon: Gauge },
  { href: "/costs", label: "Koszty", icon: BarChart3 },
  { href: "/apps", label: "Aplikacje i klucze", icon: Boxes },
  { href: "/providers", label: "Providerzy i limity", icon: KeyRound },
  { href: "/routing", label: "Routing", icon: Route },
  { href: "/pricing", label: "Cennik", icon: Tags },
];

export default function DashLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api<User>("/api/auth/me")
      .then(setUser)
      .catch(() => router.replace("/login"));
  }, [router]);

  if (!user) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <SessionProvider user={user}>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, currency, setCurrency } = useSession();

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col gap-1 border-b border-border bg-surface p-3 md:w-56 md:border-b-0 md:border-r">
        <div className="px-2 pb-3 pt-1 text-sm font-semibold">AIGateway-X</div>
        <nav className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 whitespace-nowrap rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                pathname === href && "bg-muted font-medium text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="flex flex-wrap items-center gap-3 px-2 pt-2 md:mt-auto md:flex-col md:flex-nowrap md:items-stretch md:gap-2 md:border-t md:border-border md:pt-3">
          <div className="flex w-28 rounded-md border border-border p-0.5 text-xs md:w-auto">
            {(["USD", "PLN"] as const).map((c) => (
              <button
                key={c}
                onClick={() => setCurrency(c)}
                className={cn("flex-1 rounded-sm py-1", currency === c ? "bg-muted font-medium" : "text-muted-foreground")}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="truncate text-xs text-muted-foreground" title={user.email}>
            {user.email} · {user.role}
          </div>
          <button onClick={logout} className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
            <LogOut className="h-3.5 w-3.5" /> Wyloguj
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
    </div>
  );
}
