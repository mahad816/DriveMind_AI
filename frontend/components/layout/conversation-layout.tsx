import { cn } from "@/lib/utils";

type ConversationLayoutProps = {
  children: React.ReactNode;
  className?: string;
};

/**
 * Full-height conversation canvas — replaces PageContainer on chat routes.
 * Sidebar is provided by AppShell; this is the main content column only.
 */
export function ConversationLayout({ children, className }: ConversationLayoutProps) {
  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col bg-surface-canvas",
        className,
      )}
    >
      <div className="mx-auto flex h-full min-h-0 w-full max-w-3xl flex-1 flex-col px-4 py-4 md:px-6 md:py-6">
        {children}
      </div>
    </div>
  );
}
