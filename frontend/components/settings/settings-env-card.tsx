"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { apiBaseUrl } from "@/lib/api/config";

export function SettingsEnvCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Environment (read-only)</CardTitle>
        <CardDescription>Current API wiring and feature flag notes.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-muted-foreground">
        <div className="space-y-1">
          <p className="text-xs font-medium text-foreground">Backend API</p>
          <p>
            Browser calls use <code className="rounded bg-muted px-1 py-0.5">{apiBaseUrl}</code>.
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-xs font-medium text-foreground">OAuth flow</p>
          <p>
            The connect button triggers full-page redirects to <code className="rounded bg-muted px-1 py-0.5">/api/v1/auth/google</code>.
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-xs font-medium text-foreground">Security note</p>
          <p>
            The frontend has no Google Drive credentials. Tokens are handled only by the backend.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

