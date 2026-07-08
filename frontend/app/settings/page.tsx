import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";

export default function SettingsPage() {
  return (
    <PageContainer>
      <PageHeader
        title="Settings"
        description="Connect Google Drive and configure your workspace."
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Coming in Milestone 4</CardTitle>
          <CardDescription>
            Drive connection, theme toggle, and environment details will be implemented next.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          OAuth starts via{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">GET /auth/google</code> and
          returns through the backend callback redirect.
        </CardContent>
      </Card>
    </PageContainer>
  );
}
