import { Files, Settings, type LucideIcon } from "lucide-react";

export type UtilityNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

/** Secondary navigation — knowledge library and settings only (Index demoted). */
export const utilityNavItems: UtilityNavItem[] = [
  { href: "/files", label: "Files", icon: Files },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function isChatRoute(pathname: string): boolean {
  return pathname === "/chat" || pathname.startsWith("/chat/") || pathname.startsWith("/sources");
}

export function isOnboardingRoute(pathname: string): boolean {
  return pathname === "/onboarding" || pathname.startsWith("/onboarding/");
}

export function isUtilityNavActive(pathname: string, href: string): boolean {
  if (href === "/files") {
    return pathname === "/files" || pathname.startsWith("/files/");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function isConversationActive(pathname: string, conversationId: string): boolean {
  return pathname === `/chat/${conversationId}`;
}

export function isNewChatActive(pathname: string): boolean {
  return pathname === "/chat";
}
