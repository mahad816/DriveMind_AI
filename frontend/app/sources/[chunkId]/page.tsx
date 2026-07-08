import type { Metadata } from "next";

import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";
import { SourceViewer } from "@/components/sources/source-viewer";

export const metadata: Metadata = {
  title: "Source",
};

type SourcePageProps = {
  params: Promise<{
    chunkId: string;
  }>;
};

export default async function SourcePage({ params }: SourcePageProps) {
  const { chunkId } = await params;
  return (
    <PageContainer size="lg" className="max-w-4xl">
      <PageHeader title="Source viewer" description="Full citation chunk for the grounded answer." />
      <SourceViewer chunkId={chunkId} />
    </PageContainer>
  );
}

