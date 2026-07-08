import { Files, Settings, Wand2, type LucideIcon } from "lucide-react";

export type UtilityNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

/** Secondary navigation — knowledge library, build knowledge, and settings. */
export const utilityNavItems: UtilityNavItem[] = [
  { href: "/files", label: "Files", icon: Files },
  { href: "/index", label: "Build knowledge", icon: Wand2 },
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
  if (href === "/index") {
    return pathname === "/index";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function isConversationActive(pathname: string, conversationId: string): boolean {
  return pathname === `/chat/${conversationId}`;
}

export function isNewChatActive(pathname: string): boolean {
  return pathname === "/chat";
}
