"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ExternalLink, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { useDriveStatus, useFiles } from "@/components/workspace/workspace-provider";
import { usePageTitle } from "@/components/shell/shell-context";
import { useSetupState } from "@/components/setup/use-setup";
import { Button } from "@/components/ui/button";
import { Skeleton, StatusDot } from "@/components/ui/controls";
import { takeReturnPath } from "@/lib/state/browser-memory";
import { cn } from "@/lib/utils";

const SECTIONS = [["account", "Account"], ["integrations", "Integrations"], ["appearance", "Appearance"], ["about", "About"]] as const;

export function SettingsView() {
  usePageTitle("Settings");
  const params = useSearchParams();
  const router = useRouter();
  const setup = useSetupState();
  const handled = useRef(false);
  // The backend always returns from Google to /settings?login=success. Continue where the person was.
  const returning = params.get("login") === "success";
  useEffect(() => {
    if (!returning || handled.current) return;
    const back = takeReturnPath();
    if (back) { handled.current = true; router.replace(back); return; }
    if (!setup.known) return;
    handled.current = true;
    router.replace(setup.connected === false || setup.ready === 0 ? "/welcome" : "/chat");
  }, [returning, setup, router]);
  if (returning) return null;

  return (
    <div className="mx-auto w-full max-w-5xl px-5 pb-20 pt-8 md:px-8 md:pt-10">
      <h1 className="font-serif text-display font-medium">Settings</h1>
      <div className="mt-8 grid gap-10 md:grid-cols-[11rem_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="hidden md:block">
          <ul className="sticky top-8 space-y-0.5 text-label">
            {SECTIONS.map(([id, label]) => <li key={id}><a href={`#${id}`} className="block rounded-control px-2.5 py-1.5 text-graphite hover:bg-well hover:text-ink">{label}</a></li>)}
          </ul>
        </nav>
        <div className="max-w-2xl space-y-14">
          <Account />
          <Integrations />
          <Appearance />
          <About />
        </div>
      </div>
    </div>
  );
}

function Section({ id, title, children, description }: { id: string; title: string; description?: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-8">
      <h2 id={`${id}-title`} className="font-serif text-title font-medium">{title}</h2>
      {description ? <p className="mt-1 text-label text-graphite">{description}</p> : null}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Account() {
  const session = useApplicationSession();
  const [busy, setBusy] = useState(false);
  return (
    <Section id="account" title="Account">
      <div className="flex flex-wrap items-center justify-between gap-4 border-y border-rule py-4">
        <div>
          <p className="text-body">Signed in with Google</p>
          <p className="mt-0.5 text-label text-graphite">Signing out keeps your prepared documents, conversations and Drive permission.</p>
        </div>
        <Button loading={busy} onClick={() => { setBusy(true); void session.logout(); }}>Sign out</Button>
      </div>
    </Section>
  );
}

function Integrations() {
  const session = useApplicationSession();
  const status = useDriveStatus();
  const files = useFiles();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connected = status.data?.connected;
  const prepared = files.data?.filter(f => f.status === "indexed").length ?? 0;
  const expired = connected === false && (files.data?.length ?? 0) > 0;
  const connect = async () => {
    setBusy(true); setError(null);
    try { await session.connectDrive(); } catch (e) { setError((e as Error).message); setBusy(false); }
  };
  return (
    <Section id="integrations" title="Integrations" description="Where DriveMind may read documents from. Access is always read-only.">
      <div className="space-y-4">
        <article aria-labelledby="drive-title" className={cn("rounded-panel border bg-sheet p-5", expired ? "border-caution/40" : "border-rule")}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="drive-title" className="text-body font-medium">Google Drive</h3>
              <p className="mt-1 flex items-center gap-2 text-label" aria-live="polite">
                {status.data === null && !status.error ? <Skeleton className="h-3 w-28" />
                  : status.data === null ? <><StatusDot tone="caution" />Couldn&apos;t check the connection</>
                  : connected ? <><StatusDot tone="ready" />Connected, read-only</>
                  : expired ? <><StatusDot tone="caution" />Not connected</>
                  : <><StatusDot tone="neutral" />Not connected</>}
              </p>
            </div>
            {status.data === null && status.error ? <Button size="sm" onClick={() => void status.reload()}>Try again</Button>
              : connected === false ? <Button intent="primary" loading={busy} disabled={!session.canMutate} onClick={() => void connect()}>{expired ? "Reconnect Google Drive" : "Connect Google Drive"}</Button>
              : null}
          </div>
          <p className="mt-3 text-label text-graphite">
            {expired ? `DriveMind has no Google Drive connection right now. Your ${prepared.toLocaleString()} prepared ${prepared === 1 ? "document can" : "documents can"} still be used in answers; connect again to prepare new documents or check for changes.`
              : "DriveMind reads file names and the documents you prepare. It never edits, moves or deletes anything in your Drive."}
          </p>
          {error ? <p role="alert" className="mt-2 text-label text-fault">{error}</p> : null}
          {connected ? (
            <div className="mt-4 border-t border-rule pt-4">
              <a href="https://myaccount.google.com/permissions" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-label font-medium text-archive-text hover:underline underline-offset-2">
                Manage access in your Google Account<ExternalLink className="size-3.5" aria-hidden="true" /><span className="sr-only">(opens in a new tab)</span>
              </a>
              <p className="mt-1 text-meta text-faint">Removing DriveMind there stops it reading your Drive. This page may still say Connected until DriveMind next tries to read Drive. Prepared documents and their text stay in DriveMind (they can&apos;t be removed in the app yet), and conversations stay until you delete them.</p>
            </div>
          ) : null}
        </article>
        <article aria-labelledby="gmail-title" className="rounded-panel border border-dashed border-rule p-5">
          <h3 id="gmail-title" className="text-body font-medium text-graphite">Gmail</h3>
          <p className="mt-1 text-label text-faint">Not available yet. DriveMind can&apos;t read e-mail.</p>
        </article>
      </div>
    </Section>
  );
}

function Appearance() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const options = [["light", "Light", Sun], ["dark", "Dark", Moon], ["system", "Match system", Monitor]] as const;
  return (
    <Section id="appearance" title="Appearance">
      <fieldset>
        <legend className="sr-only">Theme</legend>
        <div className="grid gap-3 sm:grid-cols-3">
          {options.map(([value, label, Icon]) => {
            const checked = mounted && theme === value;
            return (
              <label key={value} className={cn("press relative flex cursor-pointer flex-col gap-3 rounded-panel border bg-sheet p-3 transition-colors duration-150",
                checked ? "border-archive shadow-[0_0_0_1px_var(--archive)]" : "border-rule hover:border-edge/60")}>
                <input type="radio" name="theme" value={value} checked={checked} onChange={() => setTheme(value)} className="peer sr-only" />
                <ThemeSwatch kind={value} />
                <span className="flex items-center gap-2 text-label"><Icon className="size-3.5 text-graphite" aria-hidden="true" />{label}</span>
                <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-panel peer-focus-visible:shadow-[var(--focus-ring)]" />
              </label>
            );
          })}
        </div>
      </fieldset>
    </Section>
  );
}
function ThemeSwatch({ kind }: { kind: "light" | "dark" | "system" }) {
  const pane = (dark: boolean) => (
    <span className={cn("flex h-full flex-1 flex-col gap-1 p-2", dark ? "bg-[#11171e]" : "bg-[#f3f5f2]")}>
      <span className={cn("h-1.5 w-3/4 rounded-sm", dark ? "bg-[#e6ebe7]/70" : "bg-[#17202a]/70")} />
      <span className={cn("h-1.5 w-1/2 rounded-sm", dark ? "bg-[#e6ebe7]/30" : "bg-[#17202a]/25")} />
      <span className="mt-auto h-1.5 w-1/3 rounded-sm bg-[#f4de66]" />
    </span>
  );
  return <span aria-hidden="true" className="flex h-14 overflow-hidden rounded-control border border-rule">{kind === "system" ? <>{pane(false)}{pane(true)}</> : pane(kind === "dark")}</span>;
}

function About() {
  return (
    <Section id="about" title="About">
      <div className="space-y-3 text-label text-graphite">
        <p>DriveMind answers questions from the Google Drive documents you choose to prepare, and shows the passages each answer relies on.</p>
        <p>It stores your Drive file names and folders, the text of prepared documents (kept in a form that can be searched), your questions and answers, and the Google authorization that lets it read Drive. Answers come from that stored copy, not from a live Drive search, and it never changes your files.</p>
        <p className="flex flex-wrap gap-x-5 gap-y-1 pt-2">
          <Link href="/welcome?guide=1" className="font-medium text-archive-text hover:underline underline-offset-2">Setup guide</Link>
          <span className="text-faint">Version {process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1.0"}</span>
        </p>
      </div>
    </Section>
  );
}
