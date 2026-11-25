"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { ShellContext } from "@/components/shell/shell-context";
import { FOCUS_COMPOSER_EVENT } from "@/components/shell/shell-context";
import type { ShellApi } from "@/components/shell/shell-context";
import { Rail, RailContent } from "@/components/shell/rail";
import { TopBar } from "@/components/shell/top-bar";
import { ConnectionBanners } from "@/components/shell/connection-banners";
import { CommandPalette } from "@/components/shell/command-palette";
import { PreparationTray } from "@/components/preparation/preparation-tray";
import { Sheet } from "@/components/ui/dialog";
import { readPreference, writePreference } from "@/lib/state/browser-memory";

const typing = (target: EventTarget | null) => {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
};

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useApplicationSession();
  const [title, setTitle] = useState("DriveMind");
  const [palette, setPalette] = useState<{ open: boolean; query: string }>({ open: false, query: "" });
  const [navOpen, setNavOpen] = useState(false);
  const [compact, setCompact] = useState(false);

  // Rail width: a saved choice wins; otherwise compact below 1024 px (blueprint §12.1).
  useEffect(() => {
    const saved = readPreference("rail");
    setCompact(saved ? saved === "compact" : window.matchMedia("(max-width: 1023px)").matches);
  }, []);
  const toggleRail = useCallback(() => setCompact(value => { writePreference("rail", value ? "full" : "compact"); return !value; }), []);

  const api = useMemo<ShellApi>(() => ({
    setTitle, openPalette: (query = "") => setPalette({ open: true, query }), openNavigation: () => setNavOpen(true),
  }), []);

  // Close the mobile drawer whenever navigation happens.
  useEffect(() => { setNavOpen(false); }, [pathname]);

  // Global shortcuts. ⌘K / Ctrl K and "/" open search; ⇧⌘O starts a new chat.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && !event.shiftKey && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette(p => ({ open: !p.open, query: "" })); return; }
      if (event.key === "/" && !mod && !typing(event.target) && !document.querySelector("[role=dialog]")) { event.preventDefault(); setPalette({ open: true, query: "" }); return; }
      if (mod && event.shiftKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        if (pathname !== "/chat") router.push("/chat");
        requestAnimationFrame(() => window.dispatchEvent(new Event(FOCUS_COMPOSER_EVENT)));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pathname, router]);

  // Scroll memory for pages that scroll in <main> (chat keeps its own per conversation).
  const main = useRef<HTMLElement>(null);
  const positions = useRef(new Map<string, number>());
  const previous = useRef(pathname);
  useEffect(() => {
    const el = main.current;
    if (!el) return;
    positions.current.set(previous.current, el.scrollTop);
    previous.current = pathname;
    el.scrollTop = positions.current.get(pathname) ?? 0;
  }, [pathname]);

  const skipTarget = pathname.startsWith("/files") ? "Skip to library" : pathname.startsWith("/chat") ? "Skip to conversation" : "Skip to content";
  return (
    <ShellContext.Provider value={api}>
      <div className="flex h-dvh w-full overflow-hidden bg-paper text-ink" data-degraded={session.degraded || undefined}>
        <a href="#main" className="sr-only z-[80] rounded-control bg-ink px-3 py-2 text-label text-paper focus:not-sr-only focus:fixed focus:left-3 focus:top-3">{skipTarget}</a>
        <Rail compact={compact} onToggle={toggleRail} onSearch={() => api.openPalette()} />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar title={title} onMenu={() => setNavOpen(true)} />
          <ConnectionBanners />
          <main id="main" ref={main} tabIndex={-1} className="relative flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden outline-none">
            {children}
          </main>
        </div>
        <PreparationTray />
        <CommandPalette open={palette.open} initialQuery={palette.query} onOpenChange={open => setPalette(p => ({ ...p, open }))} />
        <Sheet open={navOpen} onOpenChange={setNavOpen} side="left" title="Navigation" hideTitle responsive={false} className="md:hidden">
          <div className="-mx-5 -mb-5 h-full"><RailContent compact={false} onSearch={() => { setNavOpen(false); api.openPalette(); }} inDrawer /></div>
        </Sheet>
      </div>
    </ShellContext.Provider>
  );
}
