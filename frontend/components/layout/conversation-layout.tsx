import { cn } from "@/lib/utils";

type ConversationLayoutProps = {
  children: React.ReactNode;
  className?: string;
};

/**
 * Full-height conversation canvas — full width so the scroll bar sits on the
 * right edge of the main column. Content centering is handled inside ChatInterface.
 */
export function ConversationLayout({ children, className }: ConversationLayoutProps) {
  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col bg-surface-canvas",
        className,
      )}
    >
      {children}
    </div>
  );
}
