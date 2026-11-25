"use client";
import Link from "next/link";
import { Menu as MenuIcon, SquarePen } from "lucide-react";
import { Mark } from "@/components/brand";

/** Below 768 px only: menu, current page, new chat. */
export function TopBar({ title, onMenu }: { title: string; onMenu: () => void }) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-1 border-b border-rule bg-paper px-1.5 pt-[env(safe-area-inset-top)] md:hidden">
      <button type="button" onClick={onMenu} aria-label="Open navigation" className="press grid size-11 place-items-center rounded-control text-graphite hover:bg-well">
        <MenuIcon className="size-5" aria-hidden="true" />
      </button>
      <Mark className="size-4" />
      <p className="min-w-0 flex-1 truncate px-1.5 text-label font-medium" aria-live="polite">{title}</p>
      <Link href="/chat" aria-label="New chat" className="press grid size-11 place-items-center rounded-control text-graphite hover:bg-well">
        <SquarePen className="size-[18px]" aria-hidden="true" />
      </Link>
    </header>
  );
}
