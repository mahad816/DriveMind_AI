"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Library, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings } from "lucide-react";
import type { ReactNode } from "react";
import { Wordmark } from "@/components/brand";
import { Tooltip } from "@/components/ui/tooltip";
import { Kbd, Skeleton, StatusDot } from "@/components/ui/controls";
import { ConversationList } from "@/components/shell/conversation-list";
import { useDriveStatus, useFiles } from "@/components/workspace/workspace-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { cn } from "@/lib/utils";

export function Rail({ compact, onToggle, onSearch }: { compact: boolean; onToggle: () => void; onSearch: () => void }) {
  return (
    <nav aria-label="Workspace"
      className={cn("relative hidden shrink-0 flex-col border-r border-rule bg-paper transition-[width] duration-[220ms] ease-[var(--ease-in-out)] md:flex",
        compact ? "w-[var(--rail-compact)]" : "w-[var(--rail)]")}>
      <RailContent compact={compact} onSearch={onSearch} onToggle={onToggle} />
    </nav>
  );
}

const mod = () => (typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl ");

export function RailContent({ compact, onSearch, onToggle, inDrawer }: { compact: boolean; onSearch: () => void; onToggle?: () => void; inDrawer?: boolean }) {
  const pathname = usePathname();
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cn("flex h-14 shrink-0 items-center px-3", compact ? "justify-center" : "justify-between pl-4")}>
        {compact ? null : <Link href="/chat" className="rounded-control py-1"><Wordmark /></Link>}
        {onToggle ? (
          <Tooltip content={compact ? "Expand sidebar" : "Collapse sidebar"} side="right">
            <button type="button" onClick={onToggle} aria-label={compact ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!compact}
              className="press grid size-8 place-items-center rounded-control text-graphite hover:bg-well hover:text-ink">
              {compact ? <PanelLeftOpen className="size-4" aria-hidden="true" /> : <PanelLeftClose className="size-4" aria-hidden="true" />}
            </button>
          </Tooltip>
        ) : null}
      </div>

      <div className={cn("flex shrink-0 flex-col gap-1.5 px-3 pb-3", compact && "items-center")}>
        <RailButton compact={compact} href="/chat" icon={<Plus className="size-4" />} label="New chat" emphasis
          active={pathname === "/chat"} shortcut={`⇧${mod()}O`} />
        <RailButton compact={compact} onClick={onSearch} icon={<Search className="size-4" />} label="Search" shortcut={`${mod()}K`} />
      </div>

      <div className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain", compact && "invisible")} aria-hidden={compact || undefined}>
        {compact ? null : <ConversationList inDrawer={inDrawer} />}
      </div>

      <div className={cn("flex shrink-0 flex-col gap-0.5 border-t border-rule px-3 py-3", compact && "items-center")}>
        <LibraryLink compact={compact} active={pathname.startsWith("/files")} />
        <RailButton compact={compact} href="/settings" icon={<Settings className="size-4" />} label="Settings" active={pathname === "/settings"} />
        <DriveLine compact={compact} />
      </div>
    </div>
  );
}

function RailButton({ compact, href, onClick, icon, label, active, shortcut, emphasis, trailing }: {
  compact: boolean; href?: string; onClick?: () => void; icon: ReactNode; label: string; active?: boolean; shortcut?: string; emphasis?: boolean; trailing?: ReactNode;
}) {
  const className = cn(
    "press group flex h-9 items-center gap-2.5 rounded-control text-label touch-44",
    compact ? "w-9 justify-center" : "w-full px-2.5",
    emphasis && !compact ? "border border-edge/60 bg-sheet text-ink hover:border-edge" : "text-graphite hover:bg-well hover:text-ink",
    emphasis && compact && "border border-edge/60 bg-sheet text-ink",
    active && !emphasis && "bg-well text-ink",
  );
  const content = (
    <>
      <span aria-hidden="true" className="shrink-0">{icon}</span>
      {compact ? <span className="sr-only">{label}</span> : <span className="min-w-0 flex-1 truncate text-left">{label}</span>}
      {!compact && shortcut ? <Kbd className="opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100">{shortcut}</Kbd> : null}
      {!compact ? trailing : null}
    </>
  );
  const control = href
    ? <Link href={href} className={className} aria-current={active ? "page" : undefined}>{content}</Link>
    : <button type="button" onClick={onClick} className={className}>{content}</button>;
  return compact ? <Tooltip content={shortcut ? `${label} (${shortcut})` : label} side="right">{control}</Tooltip> : control;
}

function LibraryLink({ compact, active }: { compact: boolean; active: boolean }) {
  const files = useFiles();
  const ready = files.data?.filter(f => f.status === "indexed").length;
  return (
    <RailButton compact={compact} href="/files" icon={<Library className="size-4" />} label="Library" active={active}
      trailing={ready === undefined ? (files.loading ? <Skeleton className="h-3 w-10" /> : null)
        : <span className="text-meta tabular text-faint">{ready.toLocaleString()} ready</span>} />
  );
}

/** Drive connection at a glance; opens Settings › Integrations. */
function DriveLine({ compact }: { compact: boolean }) {
  const status = useDriveStatus();
  const { degraded, offline } = useApplicationSession();
  const known = status.data !== null;
  const tone = offline || degraded ? "caution" : !known ? (status.error ? "caution" : "neutral") : status.data!.connected ? "ready" : "caution";
  const label = offline ? "Offline" : degraded ? "Reconnecting…" : !known ? (status.error ? "Drive status unknown" : "Checking Drive…")
    : status.data!.connected ? "Drive connected" : "Drive not connected";
  const link = (
    <Link href="/settings#integrations"
      className={cn("press flex h-8 items-center gap-2.5 rounded-control text-meta text-graphite hover:bg-well hover:text-ink",
        compact ? "w-9 justify-center" : "w-full px-2.5")}>
      <span className="grid w-4 place-items-center"><StatusDot tone={tone} /></span>
      {compact ? <span className="sr-only">{label}</span> : <span className="truncate">{label}</span>}
    </Link>
  );
  return compact ? <Tooltip content={label} side="right">{link}</Tooltip> : link;
}
