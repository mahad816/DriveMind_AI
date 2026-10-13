"use client";
import Link from "next/link";
import { utilityNavItems } from "@/lib/navigation";
import { UtilityNavLink } from "@/components/layout/utility-nav-link";
export function SessionNavigation({ onNavigate }: { onNavigate?: () => void }) {
  return <aside className="flex w-[260px] flex-col gap-4 border-r p-4">
    <Link href="/chat" onClick={onNavigate}>Chat</Link>
    <p className="text-sm text-muted-foreground">Saved conversations are temporarily unavailable while account-scoped history is being introduced. Existing browser data is preserved.</p>
    {utilityNavItems.map(item => <UtilityNavLink key={item.href} item={item} onNavigate={onNavigate} />)}
  </aside>;
}
