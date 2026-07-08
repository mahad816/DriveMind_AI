"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { ArrowLeft } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { isApiError } from "@/lib/api/errors";
import { getSourceChunk } from "@/lib/api/sources";
import type { SourceChunkRead } from "@/lib/api/types";

type SourceViewerProps = {
  chunkId: string;
};

function formatDate(input: string) {
  const d = new Date(input);
  if (Number.isNaN(d.getTime())) return input;
  return d.toLocaleString();
}

export function SourceViewer({ chunkId }: SourceViewerProps) {
  const {
    data: connection,
    error: connectionError,
    isLoading: connectionLoading,
  } = useConnectionStatus({
    pollIntervalMs: 0,
  });

  const isConnected = connection?.connected ?? false;

  const [data, setData] = useState<SourceChunkRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fusionScore, setFusionScore] = useState<number | null>(null);

  const fetchSource = useMemo(() => {
    return async (id: string) => {
      setIsLoading(true);
      setError(null);
      setData(null);

      try {
        const res = await getSourceChunk(id);
        setData(res);
      } catch (err) {
        const message = isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Unable to load source chunk";
        setError(message);
      } finally {
        setIsLoading(false);
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      // Only hit the source endpoint once Drive connectivity state is known.
      if (connectionLoading) return;

      if (!chunkId) {
        setError("Missing chunk id");
        setIsLoading(false);
        return;
      }

      // Query-param payload is optional; ignore if missing or invalid.
      const params = new URLSearchParams(window.location.search);
      const raw =
        params.get("fusionScore") ?? params.get("fusion_score") ?? params.get("score");
      if (raw) {
        const n = Number(raw);
        if (!Number.isNaN(n)) setFusionScore(n);
      }

      if (cancelled) return;
      if (!isConnected) {
        setIsLoading(false);
        return;
      }

      await fetchSource(chunkId);
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [chunkId, fetchSource, connectionLoading, isConnected]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link
          href="/chat"
          aria-label="Back to chat"
          className={buttonVariants({ variant: "link" })}
        >
          <ArrowLeft className="mr-2 size-4" />
          Chat
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="font-medium">Source</span>
      </div>

      {connectionError ? (
        <Alert variant="destructive">
          <AlertTitle>Connection status error</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      {!isConnected ? (
        <Alert className="border-amber-500/30 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
          <AlertTitle>Google Drive not connected</AlertTitle>
          <AlertDescription>
            Connect Drive in <Link className="underline" href="/settings">Settings</Link> to view sources.
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <CardTitle className="text-base">{data?.filename ?? "Source chunk"}</CardTitle>
              {data ? (
                <p className="text-sm text-muted-foreground">
                  {data.mime_type} • chunk #{data.chunk_index} • modified {formatDate(data.modified_at)}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="text-xs font-normal">
                chunk_id: <span className="font-mono">{chunkId}</span>
              </Badge>
              {fusionScore !== null ? (
                <Badge variant="outline" className="text-xs font-normal">
                  fusion_score: {fusionScore.toFixed(3)}
                </Badge>
              ) : null}
            </div>
          </div>
        </CardHeader>

        <CardContent>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Unable to load source</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-5 w-2/3" />
              <div className="grid gap-6 lg:grid-cols-12">
                <div className="lg:col-span-8">
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-24 w-full" />
                </div>
                <div className="lg:col-span-4">
                  <Skeleton className="h-24 w-full" />
                </div>
              </div>
            </div>
          ) : null}

          {data && !isLoading ? (
            <div className="grid gap-6 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-8">
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Full chunk text</p>
                  <Separator />
                  <div className="rounded-lg border bg-muted/20 p-3">
                    <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5">
                      {data.text}
                    </pre>
                  </div>
                </div>
              </div>

              <aside className="space-y-4 lg:col-span-4">
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Metadata</p>
                  <Separator />
                  <div className="space-y-3">
                    <div>
                      <p className="text-xs text-muted-foreground">drive_file_id</p>
                      <p className="font-mono text-sm">{data.drive_file_id}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">mime_type</p>
                      <p className="text-sm">{data.mime_type}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">chunk_index</p>
                      <p className="text-sm">{data.chunk_index}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">modified_at</p>
                      <p className="text-sm">{formatDate(data.modified_at)}</p>
                    </div>
                  </div>
                </div>
              </aside>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

