"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useServerConversations } from "@/components/providers/server-conversations-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import type { ConversationMetadata } from "@/lib/api/conversations";
import { Menu } from "@/components/ui/menu";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/controls";
import { useToast } from "@/components/ui/toast";
import { historyGroup } from "@/lib/format";
import type { HistoryGroup } from "@/lib/format";
import { cn } from "@/lib/utils";

const ORDER: HistoryGroup[] = ["Today", "Previous 7 days", "Previous 30 days", "Older"];

export function ConversationList({ inDrawer }: { inDrawer?: boolean }) {
  const { state, controller } = useServerConversations();
  const groups = useMemo(() => {
    const now = new Date();
    const map = new Map<HistoryGroup, ConversationMetadata[]>();
    for (const row of state.conversations) {
      const group = historyGroup(row.last_activity_at, now);
      map.set(group, [...(map.get(group) ?? []), row]);
    }
    return ORDER.filter(g => map.has(g)).map(g => ({ group: g, rows: map.get(g)! }));
  }, [state.conversations]);
  const [pendingDelete, setPendingDelete] = useState<ConversationMetadata | null>(null);
  const firstLoad = state.listLoading && state.conversations.length === 0;
  const listFailed = !!state.error && !state.error.conversationId && !state.creation && state.conversations.length === 0 && !state.listLoading
    && !["pending_submission", "invalid_request", "pending_creation"].includes(state.error.category);

  return (
    <div className="px-3 pb-4">
      {firstLoad ? (
        <div aria-hidden="true" className="space-y-3 px-2.5 pt-3">
          <Skeleton className="h-3 w-12" />{[80, 64, 72, 56].map(w => <Skeleton key={w} className="h-3.5" />)}
        </div>
      ) : null}
      {listFailed ? (
        <div className="mx-1 mt-2 rounded-control bg-well px-3 py-2.5 text-label">
          <p>Conversations couldn&apos;t load. Your history is safe.</p>
          <Button size="sm" intent="quiet" className="-ml-2.5 mt-1" onClick={() => void controller.refreshList()}>Try again</Button>
        </div>
      ) : null}
      {!firstLoad && !listFailed && state.conversations.length === 0 ? (
        <p className="px-2.5 pt-3 text-label text-faint">No conversations yet.</p>
      ) : null}
      {groups.map(({ group, rows }) => (
        <section key={group} className="pt-3" aria-labelledby={`history-${group}`}>
          <h2 id={`history-${group}`} className="px-2.5 pb-1 text-meta font-medium text-faint">{group}</h2>
          <ul className="space-y-px">
            {rows.map(row => <ConversationRow key={row.id} row={row} onDelete={setPendingDelete} inDrawer={inDrawer} />)}
          </ul>
        </section>
      ))}
      {state.nextListCursor !== null && state.conversations.length > 0 ? (
        <Button size="sm" intent="quiet" className="mt-2 w-full justify-start" loading={state.listLoading}
          onClick={() => void controller.loadMoreConversations()}>Show older conversations</Button>
      ) : null}
      <DeleteConversation row={pendingDelete} onClose={() => setPendingDelete(null)} />
    </div>
  );
}

function ConversationRow({ row, onDelete, inDrawer }: { row: ConversationMetadata; onDelete: (row: ConversationMetadata) => void; inDrawer?: boolean }) {
  const pathname = usePathname();
  const { controller, state } = useServerConversations();
  const { canMutate } = useApplicationSession();
  const active = pathname === `/chat/${row.id}`;
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(row.title);
  const [saving, setSaving] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const conflict = state.error?.conversationId === row.id && state.error.category === "metadata_version_conflict";
  useEffect(() => { if (editing) { setTitle(row.title); requestAnimationFrame(() => input.current?.select()); } }, [editing, row.title]);

  const save = async () => {
    const next = title.trim();
    if (!next || next === row.title) { setEditing(false); return; }
    setSaving(true);
    const ok = await controller.rename(row.id, next.slice(0, 256));
    setSaving(false);
    if (ok) setEditing(false);
  };

  if (editing) {
    return (
      <li>
        <form onSubmit={event => { event.preventDefault(); void save(); }} className="px-1 py-0.5">
          <input ref={input} value={title} onChange={e => setTitle(e.target.value)} maxLength={256} aria-label="Conversation title"
            disabled={saving} onBlur={() => { if (!saving) void save(); }}
            onKeyDown={e => { if (e.key === "Escape") { e.preventDefault(); setEditing(false); requestAnimationFrame(() => menuButton.current?.focus()); } }}
            className="h-8 w-full rounded-control border border-archive bg-sheet px-2 text-label outline-none" />
          {conflict ? <p role="alert" className="px-1 pt-1 text-meta text-fault">Renamed elsewhere. Showing the latest title.</p> : null}
        </form>
      </li>
    );
  }
  return (
    <li className="group relative">
      <Link href={`/chat/${row.id}`} aria-current={active ? "page" : undefined}
        className={cn("flex h-9 items-center rounded-control pl-2.5 pr-9 text-label touch-44",
          active ? "bg-well font-medium text-ink" : "text-graphite hover:bg-well/70 hover:text-ink")}>
        <span className="truncate" title={row.title}>{row.title}</span>
      </Link>
      <div className={cn("absolute right-1 top-1/2 -translate-y-1/2 transition-opacity duration-100",
        inDrawer || active ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 [@media(pointer:coarse)]:opacity-100")}>
        <Menu label={`Options for ${row.title}`}
          trigger={<button ref={menuButton} type="button" className="press grid size-7 place-items-center rounded-control text-graphite hover:bg-sheet hover:text-ink data-[popup-open]:bg-sheet data-[popup-open]:opacity-100"><MoreHorizontal className="size-4" aria-hidden="true" /></button>}
          items={[
            { label: "Rename", icon: <Pencil />, onSelect: () => setEditing(true), disabled: !canMutate, hint: canMutate ? undefined : "Unavailable while offline" },
            { label: "Delete", icon: <Trash2 />, danger: true, onSelect: () => onDelete(row), disabled: !canMutate, hint: canMutate ? undefined : "Unavailable while offline" },
          ]} />
      </div>
    </li>
  );
}

function DeleteConversation({ row, onClose }: { row: ConversationMetadata | null; onClose: () => void }) {
  const { controller } = useServerConversations();
  const router = useRouter();
  const pathname = usePathname();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<ConversationMetadata | null>(null);
  useEffect(() => { if (row) { setShown(row); setError(null); } }, [row]);
  const confirm = async () => {
    if (!row) return;
    setBusy(true);
    const wasOpen = pathname === `/chat/${row.id}`;
    const ok = await controller.delete(row.id);
    setBusy(false);
    if (ok) {
      onClose();
      toast("Conversation deleted");
      if (wasOpen) router.replace("/chat");
    } else {
      const conflict = controller.getSnapshot().error?.category === "metadata_version_conflict";
      setError(conflict ? "This conversation changed in another tab. Review it before deleting." : "It couldn't be deleted. Nothing was removed; try again.");
    }
  };
  return (
    <ConfirmDialog open={!!row} onOpenChange={open => { if (!open) onClose(); }} destructive busy={busy} error={error}
      title={`Delete “${shown?.title ?? ""}”?`} confirmLabel="Delete conversation"
      description="This removes its questions and answers from DriveMind. Your Google Drive is not affected."
      onConfirm={() => void confirm()} />
  );
}
