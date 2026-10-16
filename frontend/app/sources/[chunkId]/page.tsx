import type { Metadata } from "next";

import { PageShell } from "@/components/layout/page-shell";
import { SourceViewer } from "@/components/sources/source-viewer";
import { sourceCopy } from "@/lib/user-language";

export const metadata: Metadata = {
  title: sourceCopy.pageTitle,
};

type SourcePageProps = {
  searchParams?: Promise<{ conversation?: string | string[] }>;
  params: Promise<{
    chunkId: string;
  }>;
};

export default async function SourcePage({ params, searchParams }: SourcePageProps) {
  const { chunkId } = await params;
  const origin = (await searchParams)?.conversation;
  return (
    <PageShell className="source-reading-surface" size="md" title={sourceCopy.pageTitle} description={sourceCopy.pageDescription}>
      <SourceViewer chunkId={chunkId} conversationId={typeof origin === "string" ? origin : undefined} />
    </PageShell>
  );
}

