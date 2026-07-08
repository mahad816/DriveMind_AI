import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";

export default function IndexPage() {
  return (
    <PageContainer size="lg">
      <PageHeader
        title="Index"
        description="Sync Drive metadata and run the indexing pipeline."
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Coming in Milestone 5</CardTitle>
          <CardDescription>
            Pipeline controls for sync, ingest, chunk, and vector build will be added here.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Endpoints wired via the API client:{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">POST /index/sync</code>,{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">/ingest</code>,{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">/chunk</code>,{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">/build</code>.
        </CardContent>
      </Card>
    </PageContainer>
  );
}
