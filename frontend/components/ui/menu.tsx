"use client";
import { Menu as Base } from "@base-ui/react/menu";
import type { ReactElement, ReactNode } from "react";
import { cn } from "@/lib/utils";

export type MenuItemSpec = {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  /** Shown under a disabled item so the reason is never hidden (blueprint: disabled actions explain why). */
  hint?: string;
};

export function Menu({ trigger, items, align = "end", label }: { trigger: ReactElement; items: MenuItemSpec[]; align?: "start" | "end"; label: string }) {
  return (
    <Base.Root>
      <Base.Trigger render={trigger} aria-label={label} />
      <Base.Portal>
        <Base.Positioner sideOffset={6} align={align} className="z-50 outline-none">
          <Base.Popup className="anim-pop float-layer min-w-44 rounded-panel border border-rule bg-sheet p-1 outline-none">
            {items.map(item => (
              <Base.Item key={item.label} disabled={item.disabled} onClick={item.onSelect}
                className={cn(
                  "flex cursor-default select-none items-center gap-2.5 rounded-control px-2.5 py-2 text-label outline-none touch-44",
                  "data-[highlighted]:bg-well data-[disabled]:text-faint",
                  item.danger ? "text-fault" : "text-ink",
                )}>
                {item.icon ? <span aria-hidden="true" className="text-graphite [&>svg]:size-4">{item.icon}</span> : null}
                <span className="flex flex-col">
                  {item.label}
                  {item.hint ? <span className="text-meta text-faint">{item.hint}</span> : null}
                </span>
              </Base.Item>
            ))}
          </Base.Popup>
        </Base.Positioner>
      </Base.Portal>
    </Base.Root>
  );
}
