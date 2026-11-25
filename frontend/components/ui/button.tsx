import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

export type ButtonIntent = "primary" | "secondary" | "quiet" | "danger" | "danger-solid";
export type ButtonSize = "md" | "sm" | "icon" | "icon-sm";

/** Shared by <Button> and link-styled buttons so a link that acts like a button looks like one. */
export function buttonClass(intent: ButtonIntent = "secondary", size: ButtonSize = "md", className?: string) {
  return cn(
    "press inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-control font-sans font-medium",
    "disabled:cursor-not-allowed aria-disabled:cursor-not-allowed",
    size === "md" && "h-9 px-3.5 text-label touch-44",
    size === "sm" && "h-8 px-2.5 text-label",
    size === "icon" && "size-9 touch-44",
    size === "icon-sm" && "size-7",
    intent === "primary" && "bg-archive text-archive-ink hover:bg-archive-hover disabled:opacity-45",
    intent === "secondary" && "border border-edge/70 bg-sheet text-ink hover:border-edge hover:bg-well disabled:text-faint disabled:hover:bg-sheet disabled:border-rule",
    intent === "quiet" && "text-graphite hover:bg-well hover:text-ink disabled:text-faint disabled:hover:bg-transparent",
    intent === "danger" && "text-fault hover:bg-fault-wash disabled:opacity-50",
    intent === "danger-solid" && "bg-fault text-sheet hover:opacity-90 disabled:opacity-50",
    className,
  );
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  intent?: ButtonIntent;
  size?: ButtonSize;
  /** Shows a spinner, keeps the label (no width jump) and blocks repeat clicks. */
  loading?: boolean;
  icon?: ReactNode;
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { intent = "secondary", size = "md", loading = false, icon, className, children, disabled, type = "button", ...props }, ref,
) {
  return (
    <button ref={ref} type={type} className={buttonClass(intent, size, className)} disabled={disabled || loading}
      aria-busy={loading || undefined} {...props}>
      {loading ? <Spinner className="size-3.5" /> : icon}
      {children}
    </button>
  );
});
