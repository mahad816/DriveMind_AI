"use client";
import { Tooltip as Base } from "@base-ui/react/tooltip";
import type { ReactElement, ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <Base.Provider delay={450} closeDelay={60}>{children}</Base.Provider>;
}

/** Supplementary label only. Never the sole carrier of essential information. */
export function Tooltip({ content, children, side = "top", disabled }: { content: ReactNode; children: ReactElement; side?: "top" | "right" | "bottom" | "left"; disabled?: boolean }) {
  if (disabled) return children;
  return (
    <Base.Root>
      <Base.Trigger render={children} />
      <Base.Portal>
        <Base.Positioner side={side} sideOffset={8} className="z-[60]">
          <Base.Popup className="anim-pop max-w-64 rounded-control bg-ink px-2 py-1.5 text-meta text-paper">
            {content}
          </Base.Popup>
        </Base.Positioner>
      </Base.Portal>
    </Base.Root>
  );
}
