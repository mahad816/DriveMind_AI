"use client";
/** Route-level failure that keeps the shell: only the page area is replaced. */
export default function RouteError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mx-auto w-full max-w-[var(--column)] px-5 pt-[18dvh] md:px-8" role="alert">
      <h1 className="font-serif text-display font-medium">This page couldn&apos;t be shown.</h1>
      <p className="mt-3 text-body text-graphite">Your conversations and documents are safe. Try again, or use the sidebar to go elsewhere.</p>
      <button type="button" onClick={reset} className="mt-6 inline-flex h-9 items-center rounded-control border border-edge/70 bg-sheet px-3.5 text-label font-medium">Try again</button>
    </div>
  );
}
