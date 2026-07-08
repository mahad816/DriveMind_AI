import { KnowledgeLibrary } from "@/components/files/knowledge-library";
import { PageShell } from "@/components/layout/page-shell";

export const metadata = {
  title: "Files — DriveMind AI",
};

export default function FilesPage() {
  return (
    <PageShell
      size="xl"
      title="Your knowledge library"
      description="Browse, search, and ask questions about any file in your Google Drive."
    >
      <KnowledgeLibrary />
    </PageShell>
  );
}
