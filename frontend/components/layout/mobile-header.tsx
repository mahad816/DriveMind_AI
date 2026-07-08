"use client";

import { useState } from "react";
import { Menu, Sparkles } from "lucide-react";

import { ConnectionStatusBadge } from "@/components/layout/connection-status-badge";
import { NavLink } from "@/components/layout/nav-link";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { mainNavItems } from "@/lib/navigation";

export function MobileHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-4 md:hidden">
      <div className="flex items-center gap-2">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            render={
              <Button variant="ghost" size="icon-sm" aria-label="Open navigation menu">
                <Menu className="size-4" />
              </Button>
            }
          />
          <SheetContent side="left" className="w-72 p-0">
            <SheetHeader className="border-b border-border p-4 text-left">
              <SheetTitle className="flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Sparkles className="size-4" />
                </span>
                DriveMind AI
              </SheetTitle>
            </SheetHeader>
            <nav className="flex flex-col gap-1 p-3">
              {mainNavItems.map((item) => (
                <NavLink key={item.href} item={item} onNavigate={() => setOpen(false)} />
              ))}
            </nav>
            <Separator />
            <div className="flex items-center justify-between p-4">
              <span className="text-xs text-muted-foreground">Drive status</span>
              <ConnectionStatusBadge />
            </div>
          </SheetContent>
        </Sheet>
        <p className="text-sm font-semibold">DriveMind AI</p>
      </div>
      <ConnectionStatusBadge />
    </header>
  );
}
