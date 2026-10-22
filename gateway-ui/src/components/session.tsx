"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { Currency } from "@/lib/format";
import type { User } from "@/lib/api";

type Session = {
  user: User;
  currency: Currency;
  setCurrency: (c: Currency) => void;
  rate: number;
  setRate: (r: number) => void;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ user, children }: { user: User; children: React.ReactNode }) {
  const [currency, setCurrencyState] = useState<Currency>("USD");
  const [rate, setRate] = useState(4);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("agx-currency");
      if (saved === "USD" || saved === "PLN") setCurrencyState(saved);
    } catch {}
  }, []);

  const setCurrency = (c: Currency) => {
    setCurrencyState(c);
    try {
      localStorage.setItem("agx-currency", c);
    } catch {}
  };

  return (
    <SessionContext.Provider value={{ user, currency, setCurrency, rate, setRate }}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}

/** Zegar odświeżany co sekundę — do odliczania resetów okien. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
