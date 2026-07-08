"use client";

import Link from "next/link";
import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { appCopy } from "@/lib/user-language";
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
        <AlertTitle>{appCopy.connectionErrorTitle}</AlertTitle>
        <AlertDescription>{appCopy.connectionErrorBody}</AlertDescription>
      </Alert>
    );
  }

  if (data?.connected) {
    return null;
  }

  return (
    <Alert className="rounded-none border-x-0 border-t-0 border-warning/30 bg-warning/10 text-foreground">
      <AlertCircle className="size-4 text-warning" />
      <AlertTitle>{appCopy.connectionBannerTitle}</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>{appCopy.connectionBannerBody}</span>
        <Link
          href="/settings"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit shrink-0")}
        >
          {appCopy.connectionBannerCta}
        </Link>
      </AlertDescription>
    </Alert>
  );
}
