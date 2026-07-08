"use client";

import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { connectionStatusLabel } from "@/lib/user-language";
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
        {connectionStatusLabel.checking}
      </Badge>
    );
  }

  if (error) {
    return (
      <Badge variant="destructive" className={cn("text-xs font-normal", className)}>
        {connectionStatusLabel.error}
      </Badge>
    );
  }

  if (data?.connected) {
    return (
      <Badge
        variant="outline"
        className={cn("border-success/40 text-success", className)}
      >
        {connectionStatusLabel.connected}
      </Badge>
    );
  }

  return (
    <Badge variant="outline" className={cn("text-xs font-normal", className)}>
      {connectionStatusLabel.notConnected}
    </Badge>
  );
}
