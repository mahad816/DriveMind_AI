"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** Confirmations of completed user actions only. Errors that need action are shown inline, never as toasts. */
type Toast = { id: number; message: string; leaving: boolean };
const Context = createContext<((message: string) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(0);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const later = useCallback((fn: () => void, ms: number) => {
    const t = setTimeout(() => { timers.current.delete(t); fn(); }, ms);
    timers.current.add(t);
  }, []);
  const show = useCallback((message: string) => {
    const id = ++next.current;
    setToasts(list => [...list.slice(-2), { id, message, leaving: false }]);
    later(() => setToasts(list => list.map(t => t.id === id ? { ...t, leaving: true } : t)), 4000);
    later(() => setToasts(list => list.filter(t => t.id !== id)), 4160);
  }, [later]);
  useEffect(() => { const all = timers.current; return () => all.forEach(clearTimeout); }, []);
  const value = useMemo(() => show, [show]);
  return (
    <Context.Provider value={value}>
      {children}
      <div role="status" aria-live="polite" className="pointer-events-none fixed bottom-4 left-4 z-[70] flex flex-col gap-2 safe-bottom max-md:bottom-20 max-md:left-1/2 max-md:-translate-x-1/2">
        {toasts.map(toast => (
          <div key={toast.id}
            className={cn("enter-rise float-layer pointer-events-auto flex items-center gap-2 rounded-panel bg-ink px-3.5 py-2.5 text-label text-paper transition-[opacity,transform] duration-150",
              toast.leaving && "translate-y-1 opacity-0")}>
            <Check className="size-4 text-paper/80" aria-hidden="true" />
            {toast.message}
          </div>
        ))}
      </div>
    </Context.Provider>
  );
}

export function useToast() {
  const value = useContext(Context);
  if (!value) throw new Error("ToastProvider is required");
  return value;
}
