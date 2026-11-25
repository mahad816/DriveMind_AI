"use client";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { getSourceChunk } from "@/lib/api/sources";
import { isApiError } from "@/lib/api/errors";
import type { SourceChunkRead } from "@/lib/api/types";
import { useServerConversations } from "@/components/providers/server-conversations-provider";
import { useFiles } from "@/components/workspace/workspace-provider";
import { usePageTitle } from "@/components/shell/shell-context";
import { locateSnippet } from "@/lib/chat/passage";
import { driveUrl, fileTypeName } from "@/lib/copy/files";
import { conversationHref } from "@/lib/chat/source-navigation";
import { fullDate } from "@/lib/format";
import { Button, buttonClass } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/controls";

export function SourceView() {
  const { chunkId } = useParams<{ chunkId: string }>();
  const conversation = useSearchParams().get("conversation");
  const { state } = useServerConversations();
  const files = useFiles();
  const [result, setResult] = useState<{ status: "loading" | "ready" | "gone" | "error"; data?: SourceChunkRead }>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  usePageTitle(result.data?.filename ?? "Source");
  useEffect(() => {
    let live = true;
    setResult({ status: "loading" });
    getSourceChunk(chunkId).then(data => { if (live) setResult({ status: "ready", data }); },
      error => { if (live) setResult({ status: isApiError(error) && (error.status === 404 || error.status === 403) ? "gone" : "error" }); });
    return () => { live = false; };
  }, [chunkId, attempt]);

  // The cited words are known only from the answer that cited them; without it nothing is highlighted.
  const citation = state.turns.flatMap(t => t.status === "COMPLETED" ? t.citations : []).find(c => c.chunk_id === chunkId);
  const parts = result.data && citation ? locateSnippet(result.data.text, citation.snippet) : null;
  const file = result.data ? files.data?.find(f => f.id === result.data!.drive_file_id) : undefined;
  const back = conversationHref(conversation);

  return (
    <div className="mx-auto w-full max-w-[var(--column)] px-5 pb-20 pt-6 md:px-8 md:pt-10">
      <Link href={back} className="inline-flex items-center gap-1.5 text-label text-graphite hover:text-ink">
        <ArrowLeft className="size-3.5" aria-hidden="true" />{back === "/chat" ? "Back to chat" : "Back to the conversation"}
      </Link>
      {result.status === "loading" ? (
        <div className="mt-8 space-y-4" aria-hidden="true"><Skeleton className="h-7 w-2/3" /><Skeleton className="h-4" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-4/5" /></div>
      ) : result.status === "gone" ? (
        <div className="mt-8"><h1 className="font-serif text-display font-medium">This passage is no longer available.</h1>
          <p className="mt-3 text-body text-graphite">The document may have been prepared again since the answer was written, or it was removed.</p></div>
      ) : result.status === "error" ? (
        <div className="mt-8" role="alert"><h1 className="font-serif text-display font-medium">The passage couldn&apos;t load.</h1>
          <p className="mt-3 text-body text-graphite">Your conversation is unaffected.</p><Button className="mt-5" onClick={() => setAttempt(a => a + 1)}>Try again</Button></div>
      ) : result.data ? (
        <article className="mt-8">
          <h1 className="font-serif text-display font-medium [overflow-wrap:anywhere]">{result.data.filename}</h1>
          <p className="mt-2 text-label text-graphite">{fileTypeName(result.data.mime_type)}, passage {result.data.chunk_index + 1}, document modified {fullDate(result.data.modified_at)}</p>
          <blockquote className="mt-8 whitespace-pre-wrap border-l-2 border-highlight-edge pl-5 font-serif text-prose text-ink">
            {parts ? <>{parts.before}<mark className="mark text-ink">{parts.match}</mark>{parts.after}</> : result.data.text}
          </blockquote>
          <p className="mt-4 text-meta text-faint">{parts ? "The highlighted words are the ones the answer cited." : "This is one passage from the document, not the whole document."}</p>
          {file ? <a href={driveUrl(file.drive_file_id)} target="_blank" rel="noreferrer" className={buttonClass("secondary", "md", "mt-6")}>
            Open in Google Drive<ExternalLink className="size-3.5" aria-hidden="true" /><span className="sr-only">(opens in a new tab)</span></a> : null}
        </article>
      ) : null}
    </div>
  );
}
