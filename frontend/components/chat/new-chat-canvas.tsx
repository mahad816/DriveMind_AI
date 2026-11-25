"use client";
import Link from "next/link";
import { useMemo } from "react";
import { useDriveStatus, useFiles } from "@/components/workspace/workspace-provider";
import { buttonClass } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/controls";

/** The empty conversation. Nothing is created until the first question is sent. */
export function NewChatCanvas({ ready, onInsert }: { ready: number | null; onInsert: (text: string) => void }) {
  const files = useFiles();
  const status = useDriveStatus();
  const recent = useMemo(() => (files.data ?? []).filter(f => f.status === "indexed")
    .sort((a, b) => Date.parse(b.indexed_at ?? b.updated_at) - Date.parse(a.indexed_at ?? a.updated_at)).slice(0, 3), [files.data]);

  if (ready === 0) {
    const connected = status.data?.connected !== false;
    return (
      <div className="flex flex-1 flex-col justify-center py-12">
        <h1 className="max-w-[30rem] font-serif text-display font-medium">Prepare a document to start asking.</h1>
        <p className="mt-3 max-w-[34rem] text-body text-graphite">
          DriveMind answers only from documents you have prepared, so every answer can point to its source. Choose a few to begin.
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          {connected
            ? <Link href="/files?view=todo" className={buttonClass("primary")}>Choose documents</Link>
            : <Link href="/welcome" className={buttonClass("primary")}>Connect Google Drive</Link>}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-1 flex-col justify-center pb-6 pt-10">
      <h1 className="max-w-[32rem] font-serif text-display font-medium">What would you like to find in your documents?</h1>
      <p className="mt-3 text-body text-graphite">
        {ready === null ? <Skeleton className="inline-block h-3.5 w-56 align-middle" />
          : <>{ready.toLocaleString()} prepared {ready === 1 ? "document" : "documents"} can be used in answers. <Link href="/files?view=ready" className="text-archive-text underline underline-offset-2">Manage library</Link></>}
      </p>
      {recent.length ? (
        <div className="mt-6">
          <p className="text-meta text-faint">Ask about a recently prepared document</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {recent.map(file => (
              <button key={file.id} type="button" onClick={() => onInsert(`In “${file.name}”, `)}
                className="press max-w-full truncate rounded-full border border-rule bg-sheet px-3 py-1.5 text-label text-ink hover:border-edge/70 hover:bg-well touch-44"
                title={file.name}>{file.name}</button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
