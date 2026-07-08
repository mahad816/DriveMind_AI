"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { apiBaseUrl } from "@/lib/api/config";

type SettingsEnvCardProps = {
  embedded?: boolean;
};

export function SettingsEnvCard({ embedded = false }: SettingsEnvCardProps) {
  const content = (
    <div className="space-y-3 text-sm text-muted-foreground">
      <div className="space-y-1">
        <p className="text-xs font-medium text-foreground">Backend API</p>
        <p>
          Browser calls use <code className="rounded bg-muted px-1 py-0.5">{apiBaseUrl}</code>.
        </p>
      </div>
      <div className="space-y-1">
        <p className="text-xs font-medium text-foreground">OAuth flow</p>
        <p>
          Connect triggers redirects to{" "}
          <code className="rounded bg-muted px-1 py-0.5">/api/v1/auth/google</code>.
        </p>
      </div>
      <div className="space-y-1">
        <p className="text-xs font-medium text-foreground">Security note</p>
        <p>Google tokens are stored only on the backend.</p>
      </div>
    </div>
  );

  if (embedded) {
    return content;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Environment (read-only)</CardTitle>
        <CardDescription>Diagnostics for API wiring and OAuth.</CardDescription>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}
