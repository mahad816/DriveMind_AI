import type { DriveFileStatus } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { fileStatusLabel } from "@/lib/user-language";
import { cn } from "@/lib/utils";

const statusTextClass: Record<DriveFileStatus, string> = {
  discovered: "border-info/40 text-info",
  indexing: "border-warning/40 text-warning",
  indexed: "border-success/40 text-success",
  failed: "border-destructive/40 text-destructive",
  skipped: "border-muted-foreground/40 text-muted-foreground",
};

export function FileStatusBadge({ status }: { status: DriveFileStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn("text-xs font-normal", statusTextClass[status])}
    >
      {fileStatusLabel[status]}
    </Badge>
  );
}

