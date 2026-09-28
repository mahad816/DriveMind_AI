"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isUtilityNavActive, type UtilityNavItem } from "@/lib/navigation";
import { cn } from "@/lib/utils";

type UtilityNavLinkProps = {
  item: UtilityNavItem;
  onNavigate?: () => void;
  className?: string;
  compact?: boolean;
};

export function UtilityNavLink({ item, onNavigate, className, compact = false }: UtilityNavLinkProps) {
  const pathname = usePathname();
  const active = isUtilityNavActive(pathname, item.href);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-label={item.label}
      title={compact ? item.label : undefined}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-lg py-2 text-sm font-medium transition-colors",
        compact ? "justify-center px-2" : "px-3",
        active
          ? cn("border-l-2 border-primary bg-sidebar-accent text-sidebar-accent-foreground", !compact && "pl-[10px]")
          : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        className,
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!compact ? item.label : null}
    </Link>
  );
}
