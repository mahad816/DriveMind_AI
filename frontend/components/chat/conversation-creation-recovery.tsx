"use client";

import { Button } from "@/components/ui/button";

/** Presentation only: the caller retains the exact pending creation identity. */
export function ConversationCreationRecovery({ error, onRecover }: {
  error?: string | null;
  onRecover: () => void;
}) {
  return <div className="space-y-2">
    <div role="alert" className="text-sm">
      <p>We couldn&apos;t confirm the new chat. Recover it before starting another.</p>
      {error && error !== "Conversation state could not be refreshed." ? <p>{error}</p> : null}
    </div>
    <Button variant="outline" onClick={onRecover}>Recover chat</Button>
  </div>;
}
