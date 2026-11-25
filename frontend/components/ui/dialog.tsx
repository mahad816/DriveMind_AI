"use client";
import { Dialog as Base } from "@base-ui/react/dialog";
import { AlertDialog } from "@base-ui/react/alert-dialog";
import { X } from "lucide-react";
import type { ReactNode, RefObject } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type Common = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Element that receives focus when the layer closes (defaults to the opener). */
  finalFocus?: RefObject<HTMLElement | null>;
  initialFocus?: RefObject<HTMLElement | null>;
  className?: string;
  hideTitle?: boolean;
};

function CloseButton() {
  return (
    <Base.Close render={<Button intent="quiet" size="icon-sm" aria-label="Close" className="-mr-1.5" />}>
      <X className="size-4" aria-hidden="true" />
    </Base.Close>
  );
}

/** Centered dialog for short, focused tasks. */
export function Dialog({ open, onOpenChange, title, description, children, finalFocus, initialFocus, className }: Common) {
  return (
    <Base.Root open={open} onOpenChange={onOpenChange}>
      <Base.Portal>
        <Base.Backdrop className="anim-backdrop fixed inset-0 z-50 bg-overlay" />
        <Base.Popup finalFocus={finalFocus} initialFocus={initialFocus}
          className={cn("anim-dialog float-layer fixed left-1/2 top-[18dvh] z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 rounded-panel border border-rule bg-sheet p-5", className)}>
          <div className="mb-2 flex items-start justify-between gap-4">
            <Base.Title className="font-serif text-title font-medium">{title}</Base.Title>
            <CloseButton />
          </div>
          {description ? <Base.Description className="text-body text-graphite">{description}</Base.Description> : null}
          {children}
        </Base.Popup>
      </Base.Portal>
    </Base.Root>
  );
}

type ConfirmProps = Omit<Common, "children"> & {
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
};

/** Only for destructive or irreversible confirmations (blueprint §8: dialogs are rare). */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, cancelLabel = "Cancel", destructive, busy, error, onConfirm, finalFocus }: ConfirmProps) {
  return (
    <AlertDialog.Root open={open} onOpenChange={next => { if (!busy) onOpenChange(next); }}>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="anim-backdrop fixed inset-0 z-50 bg-overlay" />
        <AlertDialog.Popup finalFocus={finalFocus}
          className="anim-dialog float-layer fixed left-1/2 top-[22dvh] z-50 w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 rounded-panel border border-rule bg-sheet p-5">
          <AlertDialog.Title className="font-serif text-title font-medium">{title}</AlertDialog.Title>
          {description ? <AlertDialog.Description className="mt-2 text-body text-graphite">{description}</AlertDialog.Description> : null}
          {error ? <p role="alert" className="mt-3 text-label text-fault">{error}</p> : null}
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <AlertDialog.Close render={<Button intent="quiet" disabled={busy} />}>{cancelLabel}</AlertDialog.Close>
            <Button intent={destructive ? "danger-solid" : "primary"} loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

type SheetProps = Common & {
  side: "right" | "left" | "bottom";
  footer?: ReactNode;
  header?: ReactNode;
  /** Right sheets become bottom sheets below 768 px (blueprint §12.1). */
  responsive?: boolean;
  modal?: boolean;
  width?: "panel" | "evidence" | "rail";
};

/** Side or bottom sheet: file panel, evidence, review, mobile navigation. */
export function Sheet({ open, onOpenChange, title, description, children, finalFocus, initialFocus, side, footer, header, responsive = true, className, hideTitle, width = "panel" }: SheetProps) {
  const right = side === "right";
  return (
    <Base.Root open={open} onOpenChange={onOpenChange}>
      <Base.Portal>
        <Base.Backdrop className={cn("anim-backdrop fixed inset-0 z-50 bg-overlay", right && "md:bg-overlay/40")} />
        <Base.Popup finalFocus={finalFocus} initialFocus={initialFocus}
          className={cn(
            "fixed z-50 flex flex-col bg-sheet outline-none",
            side === "left" && "anim-sheet-left inset-y-0 left-0 w-[min(20rem,86vw)] border-r border-rule",
            side === "bottom" && "anim-sheet-bottom inset-x-0 bottom-0 max-h-[88dvh] rounded-t-panel border-t border-rule",
            right && (responsive
              ? "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-panel border-t border-rule anim-sheet-responsive md:inset-x-auto md:inset-y-0 md:right-0 md:max-h-none md:rounded-none md:border-l md:border-t-0"
              : "anim-sheet-right inset-y-0 right-0 border-l border-rule"),
            right && width === "panel" && "md:w-[var(--panel)]",
            right && width === "evidence" && "md:w-[25rem]",
            "float-layer",
            className,
          )}>
          {(side === "bottom" || (right && responsive)) ? (
            <div aria-hidden="true" className={cn("mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-rule-strong", right && "md:hidden")} />
          ) : null}
          <div className={cn("flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-4", hideTitle && "sr-only")}>
            <div className="min-w-0">
              <Base.Title className="font-serif text-title font-medium [overflow-wrap:anywhere]">{title}</Base.Title>
              {description ? <Base.Description className="mt-1 text-label text-graphite">{description}</Base.Description> : null}
            </div>
            <CloseButton />
          </div>
          {header}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5">{children}</div>
          {footer ? <div className="safe-bottom shrink-0 border-t border-rule px-5 py-3">{footer}</div> : null}
        </Base.Popup>
      </Base.Portal>
    </Base.Root>
  );
}
