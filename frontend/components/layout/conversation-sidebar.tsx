"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Files, MessageSquare, MessageSquarePlus } from "lucide-react";

import { UtilityNavLink } from "@/components/layout/utility-nav-link";
import { Separator } from "@/components/ui/separator";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { utilityNavItems } from "@/lib/navigation";
import { knowledgeStatusLabel } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type ConversationSidebarProps = {
  className?: string;
  onNavigate?: () => void;
};

export function ConversationSidebar({ className, onNavigate }: ConversationSidebarProps) {
  const router = useRouter();
  const { needsConnect, needsPrepare } = useKnowledgeStatus({ pollIntervalMs: 30_000 });

  const handleNewChat = () => {
    onNavigate?.();
    router.push("/chat");
  };

  const showSetupChip = needsConnect || needsPrepare;

  return (
    <aside
      className={cn(
        "flex h-full w-[240px] shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground",
        className,
      )}
      aria-label="App navigation"
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2.5 px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <MessageSquare className="size-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">DriveMind AI</p>
          <p className="truncate text-xs text-muted-foreground">Your knowledge OS</p>
        </div>
      </div>

      <div className="flex flex-col gap-1 px-3 pb-3">
        {/* New Chat CTA */}
        <button
          type="button"
          onClick={handleNewChat}
          className="flex w-full items-center gap-2 rounded-xl border border-primary/30 bg-primary/10 px-3 py-2.5 text-sm font-medium text-primary transition-colors hover:bg-primary/20"
        >
          <MessageSquarePlus className="size-4 shrink-0" />
          New Chat
        </button>
      </div>

      <Separator />

      {/* Primary nav — Files prominent */}
      <nav className="flex flex-col gap-0.5 p-3" aria-label="Primary navigation">
        <PrimaryNavLink
          href="/files"
          icon={Files}
          label="Files"
          description="Your knowledge library"
          onNavigate={onNavigate}
        />
      </nav>

      <Separator />

      {/* Utility nav */}
      <nav className="flex flex-col gap-1 p-3" aria-label="Utility navigation">
        {utilityNavItems
          .filter((item) => item.href !== "/files")
          .map((item) => (
            <UtilityNavLink key={item.href} item={item} onNavigate={onNavigate} />
          ))}
      </nav>

      {/* Setup chip */}
      {showSetupChip ? (
        <div className="mt-auto border-t border-sidebar-border p-3">
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs">
            <p className="font-medium text-foreground">
              {needsConnect ? "Connect Google Drive" : "Your assistant isn't ready yet"}
            </p>
            <Link
              href={needsConnect ? "/onboarding" : "/index"}
              onClick={onNavigate}
              className="mt-1 inline-block text-primary underline underline-offset-2"
            >
              {needsConnect ? "Get started →" : `${knowledgeStatusLabel.setup} →`}
            </Link>
          </div>
        </div>
      ) : (
        <div className="mt-auto border-t border-sidebar-border p-3 pb-4" />
      )}
    </aside>
  );
}

type PrimaryNavLinkProps = {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description?: string;
  onNavigate?: () => void;
};

function PrimaryNavLink({ href, icon: Icon, label, description, onNavigate }: PrimaryNavLinkProps) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
    >
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{label}</p>
        {description ? (
          <p className="truncate text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
    </Link>
  );
}
