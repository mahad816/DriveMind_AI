"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isUtilityNavActive, type UtilityNavItem } from "@/lib/navigation";
import { cn } from "@/lib/utils";

type UtilityNavLinkProps = {
  item: UtilityNavItem;
  onNavigate?: () => void;
  className?: string;
};

export function UtilityNavLink({ item, onNavigate, className }: UtilityNavLinkProps) {
  const pathname = usePathname();
  const active = isUtilityNavActive(pathname, item.href);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "border-l-2 border-primary bg-sidebar-accent pl-[10px] text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        className,
      )}
    >
      <Icon className="size-4 shrink-0" />
      {item.label}
    </Link>
  );
}
