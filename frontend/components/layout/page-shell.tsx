import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/layout/page-header";

type PageShellProps = {
  children: React.ReactNode;
  title: string;
  description?: string;
  className?: string;
  size?: "md" | "lg" | "xl";
};

const sizeClasses = {
  md: "max-w-3xl",
  lg: "max-w-5xl",
  xl: "max-w-7xl",
} as const;

/**
 * Standard page wrapper for secondary surfaces (Files, Settings, Prepare).
 */
export function PageShell({
  children,
  title,
  description,
  className,
  size = "lg",
}: PageShellProps) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col gap-6 p-6 md:p-8",
        sizeClasses[size],
        className,
      )}
    >
      <PageHeader title={title} description={description} />
      {children}
    </div>
  );
}
