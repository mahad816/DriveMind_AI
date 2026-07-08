import { AppSidebar } from "@/components/layout/app-sidebar";
import { ConnectionBanner } from "@/components/layout/connection-banner";
import { MobileHeader } from "@/components/layout/mobile-header";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-screen bg-background">
      <AppSidebar className="hidden md:flex" />
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <MobileHeader />
        <ConnectionBanner />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
