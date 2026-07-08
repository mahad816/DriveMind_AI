"use client";

import { ConversationSidebar } from "@/components/layout/conversation-sidebar";
import { ConnectionBanner } from "@/components/layout/connection-banner";
import { MobileHeader } from "@/components/layout/mobile-header";
import { OnboardingGate } from "@/components/onboarding/onboarding-gate";
import { isChatRoute, isOnboardingRoute } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { usePathname } from "next/navigation";

type AppShellProps = {
  children: React.ReactNode;
};

function MainChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const chatRoute = isChatRoute(pathname);
  const onboardingRoute = isOnboardingRoute(pathname);

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {!onboardingRoute ? <MobileHeader /> : null}
      {!chatRoute && !onboardingRoute ? <ConnectionBanner /> : null}
      <main
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          chatRoute ? "overflow-hidden" : "overflow-y-auto",
        )}
      >
        <OnboardingGate>{children}</OnboardingGate>
      </main>
    </div>
  );
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const onboardingRoute = isOnboardingRoute(pathname);

  return (
    <div className="flex h-dvh bg-background">
      {!onboardingRoute ? <ConversationSidebar className="hidden md:flex" /> : null}
      <MainChrome>{children}</MainChrome>
    </div>
  );
}
