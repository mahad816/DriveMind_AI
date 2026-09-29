"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, MessageSquare } from "lucide-react";

import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";
import { Button } from "@/components/ui/button";
import { getGoogleAuthUrl } from "@/lib/api/auth";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { markOnboardingComplete, setOnboardingOAuthPending } from "@/lib/onboarding/storage";

export function OnboardingFlow() {
  const router = useRouter();
  const { setupState, isConnected, fileStats, error, refresh } = useKnowledgeStatus({
    pollIntervalMs: 2_000,
  });
  const [preparingHere, setPreparingHere] = useState(false);

  const connected = isConnected;
  const ready = setupState === "ready";

  const handleConnect = () => {
    setOnboardingOAuthPending();
    window.location.href = getGoogleAuthUrl();
  };

  const startChatting = () => {
    markOnboardingComplete();
    router.push("/chat");
  };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center px-5 py-10 sm:px-8 md:py-16">
      <div className="mb-10 flex items-center gap-2 text-sm font-semibold text-foreground">
        <span className="flex size-8 items-center justify-center rounded-md bg-sidebar-accent text-primary" aria-hidden="true">
          <MessageSquare className="size-4" />
        </span>
        DriveMind AI
      </div>

      <header className="mb-10 max-w-xl space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">Set up your Drive knowledge</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Connect Google Drive and prepare the files DriveMind can use when answering your questions.
        </p>
      </header>

      <ol className="mb-9 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border pb-5 text-sm" aria-label="Setup steps">
        <li className={connected ? "text-foreground" : "font-medium text-primary"}>
          <span className="mr-2 inline-flex size-5 items-center justify-center rounded-full border border-current text-xs" aria-hidden="true">
            {connected ? <Check className="size-3" /> : "1"}
          </span>
          Connect Drive
        </li>
        <li className={ready ? "text-foreground" : connected ? "font-medium text-primary" : "text-muted-foreground"}>
          <span className="mr-2 inline-flex size-5 items-center justify-center rounded-full border border-current text-xs" aria-hidden="true">
            {ready ? <Check className="size-3" /> : "2"}
          </span>
          Prepare knowledge
        </li>
      </ol>

      <div className="max-w-xl space-y-5">
        {setupState === "checking" ? (
          <p className="text-sm text-muted-foreground" role="status">Checking your Drive connection…</p>
        ) : null}

        {setupState === "error" ? (
          <div className="space-y-3">
            <h2 className="text-lg font-semibold text-foreground">Knowledge status unavailable</h2>
            <p className="text-sm text-muted-foreground">{error ?? "Couldn’t check your Drive connection or files."}</p>
            <Button type="button" onClick={() => void refresh()}>Retry status check</Button>
          </div>
        ) : null}

        {setupState === "not_connected" ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Step 1</p>
              <h2 className="text-lg font-semibold text-foreground">Connect Google Drive</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                DriveMind uses supported files from your Drive to build searchable knowledge. Your Drive access is read-only.
              </p>
            </div>
            <Button type="button" onClick={handleConnect}>Connect Google Drive</Button>
            <button type="button" className="block text-sm text-muted-foreground underline underline-offset-2" onClick={() => void refresh()}>
              Check connection again
            </button>
          </div>
        ) : null}

        {(setupState === "connected_not_ready" || preparingHere) && setupState !== "error" ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Step 2 · Drive connected</p>
              <h2 className="text-lg font-semibold text-foreground">Prepare your knowledge</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Process supported Drive content so DriveMind can find and cite it in chat.
              </p>
            </div>
            <PrepareKnowledgeView
              variant="embedded"
              onPreparingChange={setPreparingHere}
              onComplete={() => void refresh()}
            />
          </div>
        ) : null}

        {setupState === "preparing" && !preparingHere ? (
          <div className="space-y-3" role="status">
            <p className="text-xs font-medium text-muted-foreground">Step 2 · Drive connected</p>
            <h2 className="text-lg font-semibold text-foreground">Preparing your knowledge…</h2>
            <p className="text-sm text-muted-foreground">
              {fileStats.indexed > 0
                ? `${fileStats.indexed} ${fileStats.indexed === 1 ? "file is" : "files are"} ready so far.`
                : "This can take a few minutes. You can return to check the status."}
            </p>
            {fileStats.indexed > 0 ? <Button type="button" onClick={startChatting}>Start chatting</Button> : null}
          </div>
        ) : null}

        {ready && !preparingHere ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <h2 className="text-lg font-semibold text-foreground">Knowledge ready</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                DriveMind can now answer using your prepared Drive knowledge.
              </p>
              <p className="text-sm tabular-nums text-muted-foreground">
                {fileStats.indexed} {fileStats.indexed === 1 ? "file" : "files"} ready
              </p>
            </div>
            <Button type="button" onClick={startChatting}>Start chatting</Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
