"use client";
import Link from "next/link";
import { DEMO_MODE } from "@/lib/demo";
import { Button, buttonVariants } from "@/components/ui/button";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";

export function PrepareKnowledgeView() {
  return DEMO_MODE ? <DemoKnowledge /> : <section className="mx-auto w-full max-w-3xl space-y-5 px-5 py-10 sm:px-8 md:py-14">
    <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
    <p className="text-sm leading-6 text-muted-foreground">Discover and browse supported Drive documents in Files. Select one document, review it, then prepare it for chat. Your existing prepared knowledge remains available.</p>
    <div className="flex flex-wrap gap-2"><Link href="/files" className={buttonVariants()}>Browse files</Link><Link href="/chat" className={buttonVariants({ variant: "outline" })}>Open chat</Link></div>
  </section>;
}
function DemoKnowledge() {
  const { setupState, fileStats, error, refresh } = useKnowledgeStatus({ pollIntervalMs: 0, includeInventory: true });

    return (
      <section className="space-y-4 p-6">
        <h1 className="text-xl font-semibold">Sample knowledge base</h1>
        <p className="text-sm text-muted-foreground">Seven fictional HarborDesk documents. No Google Drive connection is needed. Visitors cannot sync or rebuild this index.</p>
        <p role="status">{setupState === "ready" ? `${fileStats.indexed} sample files ready` : error ?? "Checking sample index…"}</p>
        <Button onClick={() => void refresh()} variant="outline">Refresh status</Button>
        <Link href="/chat" className={buttonVariants()}>Open chat</Link>
        <Link href="/files" className={buttonVariants({ variant: "outline" })}>Browse samples</Link>
      </section>
    );

}
