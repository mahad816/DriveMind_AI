"use client";

import { useState } from "react";
import { Menu } from "lucide-react";

import { ConversationSidebar } from "@/components/layout/conversation-sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";

export function MobileHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4 md:hidden">
      <div className="flex items-center gap-2">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            render={
              <Button variant="ghost" size="icon-sm" aria-label="Open navigation menu">
                <Menu className="size-4" />
              </Button>
            }
          />
          <SheetContent side="left" className="w-[280px] p-0">
            <ConversationSidebar onNavigate={() => setOpen(false)} className="w-full border-0" />
          </SheetContent>
        </Sheet>
        <p className="text-sm font-semibold">DriveMind AI</p>
      </div>
    </header>
  );
}
