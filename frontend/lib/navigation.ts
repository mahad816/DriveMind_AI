import {
  Database,
  Files,
  MessageSquare,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

export const mainNavItems: NavItem[] = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/index", label: "Index", icon: Database },
  { href: "/files", label: "Files", icon: Files },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * Determine whether a nav item should appear active for the current pathname.
 * Chat stays active for citation source drill-down routes.
 */
export function isNavItemActive(pathname: string, href: string): boolean {
  if (href === "/chat") {
    return pathname === "/chat" || pathname.startsWith("/sources");
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}
