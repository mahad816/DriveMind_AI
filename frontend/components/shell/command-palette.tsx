"use client";
import { Dialog as Base } from "@base-ui/react/dialog";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { FileText, Library, MessageSquare, Moon, Plus, Search, Settings, Sparkles, Sun, ListChecks } from "lucide-react";
import { useTheme } from "next-themes";
import { useServerConversations } from "@/components/providers/server-conversations-provider";
import { useFiles } from "@/components/workspace/workspace-provider";
import { prefillComposer } from "@/components/shell/shell-context";
import { Kbd, StatusDot } from "@/components/ui/controls";
import { matches, normalize } from "@/lib/state/library";
import { fileStatusWord, fileStatusTone } from "@/lib/copy/files";
import { cn } from "@/lib/utils";

type Item = { id: string; group: "Conversations" | "Files" | "Actions" | "Ask"; label: string; hint?: ReactNode; icon: ReactNode; run: (alt: boolean) => void };

export function CommandPalette({ open, onOpenChange, initialQuery }: { open: boolean; onOpenChange: (open: boolean) => void; initialQuery: string }) {
  const router = useRouter();
  const { state } = useServerConversations();
  const files = useFiles();
  const { resolvedTheme, setTheme } = useTheme();
  const [query, setQuery] = useState(initialQuery);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  useEffect(() => { if (open) { setQuery(initialQuery); setActive(0); } }, [open, initialQuery]);

  const go = (href: string) => { onOpenChange(false); router.push(href); };
  const items = useMemo<Item[]>(() => {
    const q = query.trim();
    const conversations = (q ? state.conversations.filter(c => normalize(c.title).includes(normalize(q))) : state.conversations).slice(0, q ? 6 : 5)
      .map<Item>(c => ({ id: `c:${c.id}`, group: "Conversations", label: c.title, icon: <MessageSquare />, run: () => go(`/chat/${c.id}`) }));
    const fileItems = q && files.data ? files.data.filter(f => matches(f, q)).slice(0, 8).map<Item>(f => ({
      id: `f:${f.id}`, group: "Files", label: f.name, icon: <FileText />,
      hint: <span className="flex items-center gap-1.5"><StatusDot tone={fileStatusTone(f.status)} />{fileStatusWord(f.status)}</span>,
      run: alt => {
        if (alt && f.status === "indexed") { onOpenChange(false); router.push("/chat"); requestAnimationFrame(() => prefillComposer(`In “${f.name}”, `)); }
        else go(`/files?file=${f.id}`);
      },
    })) : [];
    const actions: Item[] = ([
      { id: "a:new", group: "Actions", label: "New chat", icon: <Plus />, run: () => go("/chat") },
      { id: "a:library", group: "Actions", label: "Open library", icon: <Library />, run: () => go("/files") },
      { id: "a:prepare", group: "Actions", label: "Prepare documents", icon: <ListChecks />, run: () => go("/files?view=todo") },
      { id: "a:settings", group: "Actions", label: "Settings", icon: <Settings />, run: () => go("/settings") },
      { id: "a:theme", group: "Actions", label: resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        icon: resolvedTheme === "dark" ? <Sun /> : <Moon />, run: () => { setTheme(resolvedTheme === "dark" ? "light" : "dark"); onOpenChange(false); } },
    ] as Item[]).filter(a => !q || normalize(a.label).includes(normalize(q)));
    const ask: Item[] = q ? [{ id: "ask", group: "Ask", label: `Ask DriveMind: “${q}”`, icon: <Sparkles />,
      hint: "Opens a new chat with this question, not sent yet",
      run: () => { onOpenChange(false); router.push("/chat"); requestAnimationFrame(() => prefillComposer(q)); } }] : [];
    return [...conversations, ...fileItems, ...actions, ...ask];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, state.conversations, files.data, resolvedTheme]);
  useEffect(() => { setActive(a => Math.min(a, Math.max(0, items.length - 1))); }, [items.length]);
  useEffect(() => { document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" }); }, [active, listId]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setActive(a => (a + 1) % Math.max(items.length, 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive(a => (a - 1 + items.length) % Math.max(items.length, 1)); }
    else if (event.key === "Home") { event.preventDefault(); setActive(0); }
    else if (event.key === "End") { event.preventDefault(); setActive(items.length - 1); }
    else if (event.key === "Enter") { event.preventDefault(); items[active]?.run(event.metaKey || event.ctrlKey); }
  };
  const q = query.trim();
  const noMatches = q && !items.some(i => i.group !== "Ask");
  let index = -1;
  const groups = (["Conversations", "Files", "Actions", "Ask"] as const).map(group => ({ group, rows: items.filter(i => i.group === group) })).filter(g => g.rows.length);

  return (
    <Base.Root open={open} onOpenChange={onOpenChange}>
      <Base.Portal>
        <Base.Backdrop className="anim-backdrop fixed inset-0 z-50 bg-overlay" />
        <Base.Popup initialFocus={input}
          className="anim-pop float-layer fixed left-1/2 top-[12dvh] z-50 flex max-h-[min(34rem,76dvh)] w-[min(38rem,calc(100vw-1.5rem))] -translate-x-1/2 flex-col overflow-hidden rounded-panel border border-rule bg-sheet">
          <Base.Title className="sr-only">Search DriveMind</Base.Title>
          <div className="flex items-center gap-3 border-b border-rule px-4">
            <Search className="size-4 shrink-0 text-faint" aria-hidden="true" />
            <input ref={input} value={query} onChange={e => { setQuery(e.target.value); setActive(0); }} onKeyDown={onKeyDown}
              role="combobox" aria-expanded="true" aria-controls={listId} aria-autocomplete="list"
              aria-activedescendant={items.length ? `${listId}-${active}` : undefined} aria-label="Search conversations, files and actions"
              placeholder="Search conversations, file names and actions"
              className="h-13 min-w-0 flex-1 bg-transparent py-4 text-body outline-none placeholder:text-faint" />
            <Kbd>Esc</Kbd>
          </div>
          <div id={listId} role="listbox" aria-label="Results" className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {noMatches ? <p className="px-3 py-3 text-label text-graphite">No conversations or file names match “{q}”.</p> : null}
            {groups.map(({ group, rows }) => (
              <div key={group} role="group" aria-labelledby={`${listId}-${group}`} className="py-1">
                {group !== "Ask" ? <p id={`${listId}-${group}`} className="px-3 pb-1 pt-1.5 text-meta font-medium text-faint">{q || group !== "Conversations" ? group : "Recent conversations"}</p>
                  : <span id={`${listId}-${group}`} className="sr-only">Ask</span>}
                {rows.map(item => {
                  index += 1;
                  const i = index;
                  return (
                    <div key={item.id} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                      onMouseMove={() => setActive(i)} onClick={() => item.run(false)}
                      className={cn("flex cursor-default items-center gap-3 rounded-control px-3 py-2 text-label", i === active ? "bg-well text-ink" : "text-ink")}>
                      <span aria-hidden="true" className="text-graphite [&>svg]:size-4">{item.icon}</span>
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {item.hint ? <span className="shrink-0 text-meta text-faint">{item.hint}</span> : null}
                    </div>
                  );
                })}
              </div>
            ))}
            {q && files.error && !files.data ? (
              <div className="flex items-center justify-between px-3 py-2 text-label text-graphite">
                File names couldn&apos;t load.
                <button type="button" className="text-archive-text underline underline-offset-2" onClick={() => void files.reload()}>Try again</button>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-rule px-4 py-2 text-meta text-faint">
            <span><Kbd>↑</Kbd> <Kbd>↓</Kbd> to move, <Kbd>Enter</Kbd> to open</span>
            {state.nextListCursor !== null ? <span>Searching loaded conversations only</span> : null}
            <span className="ml-auto">File names, not file contents</span>
          </div>
        </Base.Popup>
      </Base.Portal>
    </Base.Root>
  );
}
