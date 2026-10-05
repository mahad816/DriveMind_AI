"use client";

import { DEMO_MODE, DEMO_SUGGESTIONS } from "@/lib/demo";

import Link from "next/link";
import { Sparkles } from "lucide-react";

import { buttonVariants, Button } from "@/components/ui/button";
import { chatCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

const suggestedQuestions = [
  "Find the latest meeting notes.",
  "Summarize a document in my Drive.",
  "Compare information across two files.",
] as const;

type EmptyStateHeroProps = {
  demoReady?: boolean;
  needsConnect: boolean;
  needsPrepare: boolean;
  isSending: boolean;
  onSuggestionClick: (question: string) => void;
  className?: string;
};

export function EmptyStateHero({
  demoReady = true,
  needsConnect,
  needsPrepare,
  isSending,
  onSuggestionClick,
  className,
}: EmptyStateHeroProps) {
  const canAsk = !needsConnect && !needsPrepare;

  if (DEMO_MODE && !demoReady) {
    return <p className="p-6 text-sm text-muted-foreground" role="status">The sample knowledge base is unavailable. Try refreshing status; no Google Drive setup is needed.</p>;
  }

  if (needsConnect) {
    return (
      <NotReadyState
        heading="Connect your knowledge"
        body="Connect Google Drive in Settings to get started."
        ctaLabel="Open Settings"
        ctaHref="/settings"
        className={className}
      />
    );
  }

  if (needsPrepare) {
    return (
      <NotReadyState
        heading={chatCopy.notReadyHeading}
        body={chatCopy.notReadyBody}
        ctaLabel={chatCopy.notReadyCta}
        ctaHref="/index"
        className={className}
      />
    );
  }

  return (
    <div
      className={cn(
        "flex h-full flex-col items-center justify-center gap-8 px-4 py-12 text-center",
        className,
      )}
    >
      {/* Brand */}
      <div className="max-w-xl space-y-4">
        {DEMO_MODE ? (
          <span className="inline-flex rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-[11px] font-medium tracking-widest text-primary shadow-[0_0_18px_color-mix(in_oklch,var(--primary)_18%,transparent)]">
            PUBLIC DEMO
          </span>
        ) : (
          <div className="flex items-center justify-center gap-2 text-primary">
            <Sparkles className="size-5" />
            <span className="text-sm font-medium tracking-wide uppercase">{chatCopy.brandName}</span>
          </div>
        )}
        <h1 className="text-balance text-2xl font-semibold tracking-tight text-foreground sm:text-hero">
          {DEMO_MODE ? "Explore the HarborDesk sample knowledge" : chatCopy.emptyHeading}
        </h1>
        <p className="mx-auto max-w-md text-pretty text-sm leading-relaxed text-muted-foreground">
          {DEMO_MODE ? "Ask grounded questions across a sample project knowledge base. Inspect citations or browse the included files." : chatCopy.emptySubheading}
        </p>
        {DEMO_MODE ? (
          <p className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span>Sample data</span><span aria-hidden="true">·</span><span>Limited public usage</span>
            <span aria-hidden="true" className="hidden sm:inline">·</span>
            <span className="basis-full sm:basis-auto">No Google Drive connection required</span>
          </p>
        ) : null}
      </div>

      {/* Suggested questions */}
      <div className="w-full max-w-lg space-y-2">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Try asking
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(DEMO_MODE ? DEMO_SUGGESTIONS : suggestedQuestions).map((question) => (
            <Button
              key={question}
              type="button"
              variant="outline"
              disabled={!canAsk || isSending}
              className="h-auto justify-start whitespace-normal rounded-xl px-4 py-3 text-left text-sm font-normal leading-snug"
              onClick={() => onSuggestionClick(question)}
            >
              {question}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}

type NotReadyStateProps = {
  heading: string;
  body: string;
  ctaLabel: string;
  ctaHref: string;
  className?: string;
};

function NotReadyState({ heading, body, ctaLabel, ctaHref, className }: NotReadyStateProps) {
  return (
    <div
      className={cn(
        "flex h-full flex-col items-center justify-center gap-6 px-4 py-12 text-center",
        className,
      )}
    >
      <div className="flex items-center justify-center gap-2 text-primary">
        <Sparkles className="size-5" />
        <span className="text-sm font-medium tracking-wide uppercase">DriveMind AI</span>
      </div>

      <div className="space-y-2">
        <h1 className="text-hero font-semibold tracking-tight text-foreground">{heading}</h1>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">{body}</p>
      </div>

      <Link href={ctaHref} className={buttonVariants({ size: "lg" })}>
        {ctaLabel}
      </Link>
    </div>
  );
}
