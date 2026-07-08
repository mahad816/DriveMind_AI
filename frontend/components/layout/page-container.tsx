import { cn } from "@/lib/utils";

type PageContainerProps = {
  children: React.ReactNode;
  className?: string;
  size?: "md" | "lg";
};

const sizeClasses = {
  md: "max-w-3xl",
  lg: "max-w-5xl",
} as const;

export function PageContainer({
  children,
  className,
  size = "md",
}: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col gap-6 p-6 md:p-8",
        sizeClasses[size],
        className,
      )}
    >
      {children}
    </div>
  );
}
