"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";
import type { CitationItem } from "@/lib/api/types";
import { AnswerProse, EvidenceContext } from "@/components/chat/answer-prose";
import type { EvidenceLink } from "@/components/chat/answer-prose";
import { EvidenceMargin } from "@/components/chat/evidence";
import { Button } from "@/components/ui/button";
import { copyTextToClipboard } from "@/lib/chat/clipboard";
import { answerForClipboard } from "@/lib/chat/passage";
import { cn } from "@/lib/utils";

export function Question({ text }: { text: string }) {
  return (
    <div className="border-l-2 border-rule-strong pl-4">
      <p className="sr-only">You asked</p>
      <p className="whitespace-pre-wrap text-body text-ink [overflow-wrap:anywhere]">{text}</p>
    </div>
  );
}

/** Wide layout: answer column plus a margin that reserves its space even before citations arrive (no layout jump). */
export function TurnFrame({ children, margin }: { children: React.ReactNode; margin?: React.ReactNode }) {
  return (
    <article className="grid grid-cols-1 gap-x-10 xl:grid-cols-[minmax(0,1fr)_var(--margin-col)]">
      <div className="min-w-0">{children}</div>
      {margin ?? <div aria-hidden="true" className="hidden xl:block" />}
    </article>
  );
}

export function CompletedTurn({ id, question, answer, citations, conversationId, onOpenSources, wide }: {
  id: string; question: string; answer: string; citations: readonly CitationItem[]; conversationId: string | null;
  onOpenSources: (turnId: string, citations: readonly CitationItem[], focus: number | null) => void; wide: boolean;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(false), 1500); return () => clearTimeout(t); }, [copied]);
  const link = useMemo<EvidenceLink>(() => ({
    turnId: id, active, setActive, count: citations.length,
    open: n => { if (wide) { setExpanded(n); setActive(n); } else onOpenSources(id, citations, n); },
  }), [id, active, citations, wide, onOpenSources]);
  const files = new Set(citations.map(c => c.drive_file_id)).size;

  return (
    <EvidenceContext.Provider value={link}>
      <TurnFrame margin={citations.length ? <EvidenceMargin citations={citations} turnId={id} active={active} setActive={setActive}
        expanded={expanded} setExpanded={setExpanded} conversationId={conversationId} /> : undefined}>
        <Question text={question} />
        <div className="mt-5">
          <p className="sr-only">DriveMind answered</p>
          <AnswerProse text={answer} count={citations.length} />
          {citations.length === 0 ? (
            <p className="mt-4 border-l-2 border-rule pl-3 text-label text-graphite">
              This answer doesn&apos;t cite any of your prepared documents, so treat it with care.{" "}
              <Link href="/files?view=ready" className="text-archive-text underline underline-offset-2">See what&apos;s ready</Link>
            </p>
          ) : null}
        </div>
        <div className="mt-3 flex items-center gap-1 text-meta">
          <Button intent="quiet" size="sm" className="-ml-2.5 h-7 text-meta"
            icon={copied ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
            onClick={async () => { if (await copyTextToClipboard(answerForClipboard(answer, citations.map(c => c.filename)))) setCopied(true); }}>
            {copied ? "Copied" : "Copy"}
          </Button>
          {citations.length ? (
            <Button intent="quiet" size="sm" className={cn("h-7 text-meta", wide && "xl:hidden")} onClick={() => onOpenSources(id, citations, null)}>
              {citations.length} {citations.length === 1 ? "source" : "sources"}{files < citations.length ? ` from ${files} ${files === 1 ? "document" : "documents"}` : ""}
            </Button>
          ) : null}
          <span className="sr-only" role="status">{copied ? "Answer copied" : ""}</span>
        </div>
      </TurnFrame>
    </EvidenceContext.Provider>
  );
}

export type PendingPhase = "searching" | "validating" | "generating";
export function PendingTurn({ question, phase, provisional, action }: { question: string; phase: PendingPhase | "timer"; provisional?: string; action?: React.ReactNode }) {
  // Non-streaming has no progress events: two honest labels on a timer, no invented percentage.
  const [late, setLate] = useState(false);
  useEffect(() => { if (phase !== "timer") return; const t = setTimeout(() => setLate(true), 6000); return () => clearTimeout(t); }, [phase]);
  const label = phase === "validating" || (phase === "timer" && late) ? "Checking the answer against your documents…"
    : phase === "generating" ? "Writing the answer…" : "Searching your documents…";
  return (
    <TurnFrame>
      <Question text={question} />
      <div className="mt-5" aria-busy="true">
        {provisional ? <AnswerProse text={provisional} count={0} provisional /> : null}
        <div className={cn("flex flex-wrap items-center gap-3", provisional && "mt-3")}>
          <p role="status" className="flex items-center gap-2.5 text-label text-graphite">
            <span aria-hidden="true" className="flex gap-1">{[0, 1, 2].map(i => <span key={i} className="size-1 animate-pulse rounded-full bg-archive [animation-duration:1.2s]" style={{ animationDelay: `${i * 160}ms` }} />)}</span>
            {label}
          </p>
          {action}
        </div>
      </div>
    </TurnFrame>
  );
}

/** Every non-answer outcome: what happened, whether anything changed, and the safe next step. */
export function NoticeTurn({ question, tone, title, body, actions }: {
  question: string; tone: "fault" | "neutral" | "caution"; title: string; body?: string; actions?: React.ReactNode;
}) {
  return (
    <TurnFrame>
      <Question text={question} />
      <div role={tone === "fault" ? "alert" : "status"} className={cn("mt-5 rounded-panel border px-4 py-3",
        tone === "fault" ? "border-fault/25 bg-fault-wash" : tone === "caution" ? "border-caution/25 bg-caution-wash" : "border-rule bg-sheet")}>
        <p className="text-label font-medium text-ink">{title}</p>
        {body ? <p className="mt-1 text-label text-graphite">{body}</p> : null}
        {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </TurnFrame>
  );
}
