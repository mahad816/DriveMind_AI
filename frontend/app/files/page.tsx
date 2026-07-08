import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";

export default function FilesPage() {
  return (
    <PageContainer size="lg">
      <PageHeader
        title="Files"
        description="Browse synced Drive files and indexing status."
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Coming in Milestone 6</CardTitle>
          <CardDescription>
            A searchable file table with status badges and per-file re-ingest actions will appear
            here.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Data source:{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">GET /files</code>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
