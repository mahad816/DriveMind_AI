"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";

type OnboardingGateProps = {
  children: React.ReactNode;
};

const BYPASS_PREFIXES = ["/onboarding", "/settings", "/index", "/prepare", "/sources"];

export function OnboardingGate({ children }: OnboardingGateProps) {
  const pathname = usePathname();

  if (pathname === "/" || BYPASS_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return children;
  }

  return <KnowledgeGate>{children}</KnowledgeGate>;
}

function KnowledgeGate({ children }: OnboardingGateProps) {
  const router = useRouter();
  const { setupState, isReady } = useKnowledgeStatus({ pollIntervalMs: 0 });

  useEffect(() => {
    if (!isReady && (setupState === "not_connected" || setupState === "connected_not_ready" || setupState === "preparing")) {
      router.replace("/onboarding");
    }
  }, [isReady, router, setupState]);

  if (setupState === "checking") {
    return <p className="p-6 text-sm text-muted-foreground" role="status">Checking your Drive knowledge…</p>;
  }
  if (!isReady && (setupState === "not_connected" || setupState === "connected_not_ready" || setupState === "preparing")) {
    return <p className="p-6 text-sm text-muted-foreground" role="status">Opening setup…</p>;
  }

  return children;
}

export function OnboardingAwareHomeRedirect() {
  const router = useRouter();
  const { setupState, error, refresh } = useKnowledgeStatus({ pollIntervalMs: 0 });

  useEffect(() => {
    if (setupState === "ready") {
      router.replace("/chat");
    } else if (setupState === "not_connected" || setupState === "connected_not_ready" || setupState === "preparing") {
      router.replace("/onboarding");
    }
  }, [router, setupState]);

  if (setupState === "error") {
    return (
      <div className="mx-auto w-full max-w-md space-y-3 p-6" role="alert">
        <h1 className="text-lg font-semibold text-foreground">Knowledge status unavailable</h1>
        <p className="text-sm text-muted-foreground">{error ?? "Couldn’t check your Drive connection or files."}</p>
        <Button type="button" onClick={() => void refresh()}>Retry status check</Button>
      </div>
    );
  }

  return <p className="p-6 text-sm text-muted-foreground" role="status">Checking your Drive knowledge…</p>;
}
