import type { DriveFileStatus } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { fileStatusLabel } from "@/lib/user-language";
import { cn } from "@/lib/utils";

const statusTextClass: Record<DriveFileStatus, string> = {
  discovered: "text-muted-foreground",
  indexing: "text-muted-foreground",
  indexed: "text-success",
  failed: "text-destructive",
  skipped: "text-muted-foreground",
};

export function FileStatusBadge({ status }: { status: DriveFileStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn("shrink-0 border-transparent bg-transparent px-1 text-xs font-normal", statusTextClass[status])}
    >
      {fileStatusLabel[status]}
    </Badge>
  );
}
