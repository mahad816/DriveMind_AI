"use client";
import { useEffect, useState } from "react";
import { Wordmark } from "@/components/brand";
import { Button } from "@/components/ui/button";

type Props = {
  status: "checking" | "signed_out" | "unavailable" | "ready";
  error: string | null;
  onLogin: () => void;
  onRetry: () => void;
};

/** The only screen a signed-out visitor sees. Explains the product by showing its defining element. */
export function SignInScreen({ status, error, onLogin, onRetry }: Props) {
  // "Checking…" only appears if the check is slow; a fast check never flashes text.
  const [slow, setSlow] = useState(false);
  const [starting, setStarting] = useState(false);
  useEffect(() => {
    if (status !== "checking") { setSlow(false); setStarting(false); return; }
    const timer = setTimeout(() => setSlow(true), 300);
    return () => clearTimeout(timer);
  }, [status]);

  return (
    <main aria-label="Application sign-in" className="min-h-dvh overflow-y-auto bg-paper text-ink">
      <div className="mx-auto grid min-h-dvh w-full max-w-6xl grid-cols-1 content-center gap-12 px-6 py-12 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,27rem)] lg:gap-20 lg:py-20">
        <section className="max-w-xl">
          <Wordmark />
          <h1 className="mt-10 font-serif text-[2.125rem] font-medium leading-[1.15] tracking-[-0.015em] sm:text-[2.625rem]">
            Ask questions about your Drive documents.
          </h1>
          <p className="mt-5 max-w-[34rem] text-[1.0625rem] leading-7 text-graphite">
            DriveMind reads the contents only of documents you choose, and answers with the exact passages it relied on, so every claim can be checked.
          </p>

          <ol className="mt-9 space-y-3 text-body">
            {["Sign in with your Google account.", "Connect Google Drive with read-only access.", "Choose documents to prepare, then ask."].map((step, i) => (
              <li key={step} className="flex gap-3">
                <span aria-hidden="true" className="mt-px grid size-5 shrink-0 place-items-center rounded-full border border-edge/70 text-meta tabular text-graphite">{i + 1}</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>

          <div className="mt-10 min-h-28" aria-live="polite">
            {status === "checking" ? (
              <p role="status" className={slow ? "enter-fade text-body text-graphite" : "sr-only"}>Checking your sign-in…</p>
            ) : null}
            {error ? <p role={status === "unavailable" ? "alert" : "status"} className="mb-4 max-w-md text-body text-ink">{error}</p> : null}
            {status === "signed_out" ? (
              <>
                <Button intent="primary" className="h-11 px-5 text-body" loading={starting}
                  onClick={() => { setStarting(true); onLogin(); }}>Sign in with Google</Button>
                <p className="mt-4 max-w-md text-label text-graphite">
                  Signing in creates your DriveMind session. You will connect Google Drive separately, and DriveMind never edits or deletes your files.
                </p>
              </>
            ) : null}
            {status === "unavailable" ? <Button intent="secondary" onClick={onRetry}>Try again</Button> : null}
          </div>
        </section>

        <figure className="relative hidden self-center sm:block" aria-labelledby="specimen-caption">
          <Specimen />
          <figcaption id="specimen-caption" className="mt-3 text-meta text-faint">An example answer and the passage it cites. Example content.</figcaption>
        </figure>
      </div>
    </main>
  );
}

/** Static illustration of an answer with its evidence in the margin. Fictional content, not user data. */
function Specimen() {
  const [on, setOn] = useState(false);
  useEffect(() => { const t = setTimeout(() => setOn(true), 450); return () => clearTimeout(t); }, []);
  return (
    <div aria-hidden="true" className="rounded-panel border border-rule bg-sheet p-6 shadow-[0_1px_0_var(--rule)]">
      <p className="text-label text-graphite">Which districts stay hot despite their trees?</p>
      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_9.5rem] gap-5">
        <p className="font-serif text-[1.0625rem] leading-7">
          Harbour and Old Mill sit above the trend: both have high canopy cover but surfaces that stay hot
          <Sup on={on}>1</Sup>, most likely because of dark roofing and wide car parks.
        </p>
        <div className="border-l border-rule pl-4">
          <p className="flex items-center gap-1.5 text-meta font-medium text-graphite"><Sup on={on}>1</Sup> Canopy survey</p>
          <p className="mt-1.5 font-serif text-[0.875rem] leading-[1.35rem]">
            <span className={`mark mark-swipe ${on ? "is-on" : ""}`}>both have high canopy cover but surfaces that stay hot</span>
          </p>
        </div>
      </div>
    </div>
  );
}
function Sup({ children, on }: { children: string; on: boolean }) {
  return (
    <span className={`mx-0.5 inline-grid h-[1.15rem] min-w-[1.15rem] place-items-center rounded-[5px] align-[0.12em] font-sans text-[0.6875rem] font-semibold tabular transition-colors duration-300 ${on ? "bg-highlight text-ink" : "bg-archive-wash text-archive-text"}`}>{children}</span>
  );
}
