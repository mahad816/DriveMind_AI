"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";

import { buttonVariants, Button } from "@/components/ui/button";
import { chatCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

/** Suggested questions that demonstrate the product's power to a recruiter or new user. */
const suggestedQuestions = [
  "Summarize my most recent resume.",
  "What projects have I worked on?",
  "Find everything related to machine learning.",
  "Which files mention LangGraph or RAG?",
  "What did I build at my last internship?",
  "Show me my certificates and credentials.",
] as const;

type EmptyStateHeroProps = {
  needsConnect: boolean;
  needsPrepare: boolean;
  isSending: boolean;
  onSuggestionClick: (question: string) => void;
  className?: string;
};

export function EmptyStateHero({
  needsConnect,
  needsPrepare,
  isSending,
  onSuggestionClick,
  className,
}: EmptyStateHeroProps) {
  const canAsk = !needsConnect && !needsPrepare;

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
      <div className="space-y-2">
        <div className="flex items-center justify-center gap-2 text-primary">
          <Sparkles className="size-5" />
          <span className="text-sm font-medium tracking-wide uppercase">
            {chatCopy.brandName}
          </span>
        </div>
        <h1 className="text-hero font-semibold tracking-tight text-foreground">
          {chatCopy.emptyHeading}
        </h1>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">
          {chatCopy.emptySubheading}
        </p>
      </div>

      {/* Suggested questions */}
      <div className="w-full max-w-lg space-y-2">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Try asking
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {suggestedQuestions.map((question) => (
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
