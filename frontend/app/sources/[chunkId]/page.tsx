import type { Metadata } from "next";

import { PageShell } from "@/components/layout/page-shell";
import { SourceViewer } from "@/components/sources/source-viewer";
import { sourceCopy } from "@/lib/user-language";

export const metadata: Metadata = {
  title: sourceCopy.pageTitle,
};

type SourcePageProps = {
  params: Promise<{
    chunkId: string;
  }>;
};

export default async function SourcePage({ params }: SourcePageProps) {
  const { chunkId } = await params;
  return (
    <PageShell size="md" title={sourceCopy.pageTitle} description={sourceCopy.pageDescription}>
      <SourceViewer chunkId={chunkId} />
    </PageShell>
  );
}

