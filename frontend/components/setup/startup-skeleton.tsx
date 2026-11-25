import { Skeleton } from "@/components/ui/controls";

/** One quiet frame while the destination is decided; it shares the chat canvas's proportions, so nothing jumps. */
export function StartupSkeleton() {
  return (
    <div aria-hidden="true" className="mx-auto flex w-full max-w-[var(--column)] flex-1 flex-col justify-end px-5 pb-28 md:px-8">
      <Skeleton className="h-7 w-80 max-w-full" />
      <Skeleton className="mt-4 h-3.5 w-60" />
    </div>
  );
}
