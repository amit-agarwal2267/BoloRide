"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const Clock = createContext<Date | null>(null);
export function PhoneClock({ children }: { children: ReactNode }) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      clearTimeout(timer);
      setNow(new Date());
      timer = setTimeout(tick, 60_000 - Date.now() % 60_000);
    };
    tick();
    document.addEventListener("visibilitychange", tick);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", tick); };
  }, []);
  return <Clock.Provider value={now}>{children}</Clock.Provider>;
}
export function useClock() {
  const now = useContext(Clock);
  return {
    time: now ? new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(now) : "—:—",
    date: now ? new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(now) : "",
  };
}
