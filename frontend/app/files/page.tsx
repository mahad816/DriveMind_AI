import { KnowledgeLibrary } from "@/components/files/knowledge-library";
import { PageShell } from "@/components/layout/page-shell";
import { filesCopy } from "@/lib/user-language";

export const metadata = {
  title: "Files — DriveMind AI",
};

export default function FilesPage() {
  return (
    <PageShell
      size="xl"
      className="px-5 py-10 sm:px-8 md:h-full md:min-h-0 md:overflow-hidden md:py-14"
      title={filesCopy.pageTitle}
      description={filesCopy.pageDescription}
    >
      <KnowledgeLibrary />
    </PageShell>
  );
}
