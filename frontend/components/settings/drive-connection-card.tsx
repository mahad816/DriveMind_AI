"use client";

import { useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { ConnectionStatusBadge } from "@/components/layout/connection-status-badge";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { getGoogleAuthUrl } from "@/lib/api/auth";
import type { DriveSyncStatusResponse } from "@/lib/api/types";

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) {
    return "—";
  }
  return d.toLocaleString();
}

function StatusSection({ status }: { status: DriveSyncStatusResponse | null }) {
  if (!status?.job) {
    return null;
  }

  return (
    <div className="space-y-2 text-sm text-muted-foreground">
      <p className="flex items-center justify-between gap-4">
        <span>Last sync</span>
        <span className="font-medium text-foreground">{status.job.status}</span>
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <p className="flex items-center justify-between gap-4">
          <span>Started</span>
          <span className="font-medium text-foreground">
            {formatDateTime(status.job.started_at)}
          </span>
        </p>
        <p className="flex items-center justify-between gap-4">
          <span>Completed</span>
          <span className="font-medium text-foreground">
            {formatDateTime(status.job.completed_at)}
          </span>
        </p>
      </div>
      {status.job.error ? (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-destructive">
          {status.job.error}
        </p>
      ) : null}
    </div>
  );
}

export function DriveConnectionCard() {
  const searchParams = useSearchParams();

  const connectedParam = searchParams.get("connected");
  const emailParam = searchParams.get("email");
  const errorParam = searchParams.get("error");

  const connectedRequested = connectedParam === "true";

  const { data, isLoading, error, refetch } = useConnectionStatus({
    pollIntervalMs: 30_000,
  });

  useEffect(() => {
    if (connectedRequested) {
      void refetch();
    }
  }, [connectedRequested, refetch]);

  const status = useMemo(() => {
    return data;
  }, [data]);

  const connectUrl = getGoogleAuthUrl();

  const label = data?.connected ? "Reconnect Google Drive" : "Connect Google Drive";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Google Drive connection</CardTitle>
        <CardDescription>
          Connect Drive to sync files, retrieve grounded answers, and open citations.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <ConnectionStatusBadge />
            <div>
              <p className="text-sm font-medium text-foreground">
                {data?.connected ? "Connected" : "Not connected"}
              </p>
              {data?.connected && emailParam ? (
                <p className="text-xs text-muted-foreground">{emailParam}</p>
              ) : null}
            </div>
          </div>
          <a
            href={connectUrl}
            className={buttonVariants({ variant: "default", size: "default" })}
          >
            {label}
          </a>
        </div>

        {connectedRequested ? (
          <Alert
            className="border-emerald-500/40 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/20 dark:text-emerald-100"
            variant="default"
          >
            <AlertTitle>Drive connected</AlertTitle>
            <AlertDescription>
              You can now run indexing and ask questions in the Chat page.
            </AlertDescription>
          </Alert>
        ) : null}

        {errorParam ? (
          <Alert variant="destructive">
            <AlertTitle>OAuth error</AlertTitle>
            <AlertDescription>{errorParam}</AlertDescription>
          </Alert>
        ) : null}

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Connection status failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {isLoading && !status ? (
          <p className="text-sm text-muted-foreground">Checking connection status…</p>
        ) : (
          <StatusSection status={status} />
        )}

        <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">API wiring</p>
          <p>
            Browser requests go to <code className="rounded bg-muted px-1 py-0.5">/api/v1</code> via
            Next.js proxy rewrites.
          </p>
          <p>
            Backend is exposed behind rewrites; OAuth redirects back to this page on success.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

