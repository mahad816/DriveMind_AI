import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";
import { FilesBrowser } from "@/components/files/files-browser";

export default function FilesPage() {
  return (
    <PageContainer size="lg" className="max-w-7xl">
      <PageHeader
        title="Files"
        description="Browse synced Drive files and indexing status."
      />

      <FilesBrowser />
    </PageContainer>
  );
}
