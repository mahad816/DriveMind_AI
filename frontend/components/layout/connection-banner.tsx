"use client";

import Link from "next/link";
import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { cn } from "@/lib/utils";

export function ConnectionBanner() {
  const { data, isLoading, error } = useConnectionStatus({ pollIntervalMs: 30_000 });

  if (isLoading && !data) {
    return null;
  }

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-none border-x-0 border-t-0">
        <AlertCircle className="size-4" />
        <AlertTitle>Unable to reach the API</AlertTitle>
        <AlertDescription>
          {error}. Ensure the backend is running on port 8000 and the frontend proxy is active.
        </AlertDescription>
      </Alert>
    );
  }

  if (data?.connected) {
    return null;
  }

  return (
    <Alert className="rounded-none border-x-0 border-t-0 border-amber-500/30 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
      <AlertCircle className="size-4 text-amber-600 dark:text-amber-400" />
      <AlertTitle>Google Drive not connected</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>Connect your Drive account to sync files and use chat.</span>
        <Link
          href="/settings"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit shrink-0")}
        >
          Go to Settings
        </Link>
      </AlertDescription>
    </Alert>
  );
}
