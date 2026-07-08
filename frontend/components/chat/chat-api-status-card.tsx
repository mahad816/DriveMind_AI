"use client";

import { useEffect, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getHealth } from "@/lib/api/health";
import { isApiError } from "@/lib/api/errors";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";

export function ChatApiStatusCard() {
  const { data: connection, isLoading: connectionLoading, error: connectionError } =
    useConnectionStatus({ pollIntervalMs: 0 });
  const [healthStatus, setHealthStatus] = useState<string | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const health = await getHealth();
        if (!cancelled) {
          setHealthStatus(health.status);
          setHealthError(null);
        }
      } catch (error) {
        if (!cancelled) {
          setHealthStatus(null);
          setHealthError(
            isApiError(error) ? error.detail : "Unable to reach backend health endpoint",
          );
        }
      }
    }

    void loadHealth();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">API wiring (Milestone 2)</CardTitle>
        <CardDescription>
          Typed client calls go through the same-origin proxy at{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">/api/v1</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        <p>
          Backend health:{" "}
          <span className="font-medium text-foreground">
            {healthStatus ?? (healthError ? "unavailable" : "checking…")}
          </span>
        </p>
        <p>
          Drive connection:{" "}
          <span className="font-medium text-foreground">
            {connectionLoading && !connection
              ? "checking…"
              : connectionError
                ? "error"
                : connection?.connected
                  ? "connected"
                  : "not connected"}
          </span>
        </p>
        {healthError ? <p className="text-destructive">{healthError}</p> : null}
        {connectionError ? <p className="text-destructive">{connectionError}</p> : null}
      </CardContent>
    </Card>
  );
}
