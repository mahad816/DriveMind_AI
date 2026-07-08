"use client";

import { Sparkles } from "lucide-react";

import { ConnectionStatusBadge } from "@/components/layout/connection-status-badge";
import { NavLink } from "@/components/layout/nav-link";
import { Separator } from "@/components/ui/separator";
import { mainNavItems } from "@/lib/navigation";
import { cn } from "@/lib/utils";

type AppSidebarProps = {
  className?: string;
};

export function AppSidebar({ className }: AppSidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-full w-60 shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground",
        className,
      )}
    >
      <div className="flex h-14 items-center gap-2 px-4">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles className="size-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">DriveMind AI</p>
          <p className="truncate text-xs text-muted-foreground">Personal Drive RAG</p>
        </div>
      </div>

      <Separator />

      <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="Main navigation">
        {mainNavItems.map((item) => (
          <NavLink key={item.href} item={item} />
        ))}
      </nav>

      <div className="border-t border-sidebar-border p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">Drive status</span>
          <ConnectionStatusBadge />
        </div>
      </div>
    </aside>
  );
}
