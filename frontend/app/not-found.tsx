import Link from "next/link";
export default function NotFound() {
  return (
    <div className="mx-auto w-full max-w-[var(--column)] px-5 pt-[18dvh] md:px-8">
      <h1 className="font-serif text-display font-medium">This page doesn&apos;t exist.</h1>
      <p className="mt-3 text-body text-graphite">The link may be out of date.</p>
      <Link href="/chat" className="mt-6 inline-flex h-9 items-center rounded-control bg-archive px-3.5 text-label font-medium text-archive-ink">Go to chat</Link>
    </div>
  );
}
