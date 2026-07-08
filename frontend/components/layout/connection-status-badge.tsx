"use client";

import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type ConnectionStatusBadgeProps = {
  className?: string;
};

export function ConnectionStatusBadge({ className }: ConnectionStatusBadgeProps) {
  const { data, isLoading, error } = useConnectionStatus({ pollIntervalMs: 30_000 });

  if (isLoading && !data) {
    return (
      <Badge variant="outline" className={cn("text-xs font-normal", className)}>
        Checking…
      </Badge>
    );
  }

  if (error) {
    return (
      <Badge variant="destructive" className={cn("text-xs font-normal", className)}>
        API error
      </Badge>
    );
  }

  if (data?.connected) {
    return (
      <Badge
        variant="outline"
        className={cn("border-emerald-500/40 text-emerald-700 dark:text-emerald-400", className)}
      >
        Connected
      </Badge>
    );
  }

  return (
    <Badge variant="outline" className={cn("text-xs font-normal", className)}>
      Not connected
    </Badge>
  );
}
