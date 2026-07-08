"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, MessageSquare } from "lucide-react";

import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";
import { Button, buttonVariants } from "@/components/ui/button";
import { getGoogleAuthUrl } from "@/lib/api/auth";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import {
  markOnboardingComplete,
  setOnboardingOAuthPending,
} from "@/lib/onboarding/storage";
import { onboardingCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type OnboardingStep = "welcome" | "connect" | "prepare" | "ready";

const FIRST_QUESTIONS = [
  "Summarize my most recent resume.",
  "What projects have I worked on?",
  "Find everything related to machine learning.",
] as const;

function stepFromParam(value: string | null): OnboardingStep | null {
  if (value === "welcome" || value === "connect" || value === "prepare" || value === "ready") {
    return value;
  }
  return null;
}

export function OnboardingFlow() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialStep = stepFromParam(searchParams.get("step")) ?? "welcome";

  const [step, setStep] = useState<OnboardingStep>(initialStep);
  const { data: connection, refetch: refetchConnection } = useConnectionStatus({
    pollIntervalMs: 2_000,
  });
  const { isReady, refresh: refreshKnowledge } = useKnowledgeStatus({ pollIntervalMs: 0 });

  const isConnected = connection?.connected ?? false;

  useEffect(() => {
    const paramStep = stepFromParam(searchParams.get("step"));
    if (paramStep) {
      setStep(paramStep);
    }
  }, [searchParams]);

  useEffect(() => {
    if (step === "connect" && isConnected) {
      setStep("prepare");
    }
  }, [isConnected, step]);

  useEffect(() => {
    if (step === "prepare" && isReady) {
      setStep("ready");
    }
  }, [isReady, step]);

  const stepIndex = useMemo(() => {
    const order: OnboardingStep[] = ["welcome", "connect", "prepare", "ready"];
    return order.indexOf(step);
  }, [step]);

  const handleConnect = () => {
    setOnboardingOAuthPending();
    window.location.href = getGoogleAuthUrl();
  };

  const finishOnboarding = (question?: string) => {
    markOnboardingComplete();
    if (question) {
      router.push(`/chat?ask=${encodeURIComponent(question)}`);
      return;
    }
    router.push("/chat");
  };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-lg flex-col justify-center gap-8 px-4 py-10 md:py-16">
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
        {["Welcome", "Connect", "Set up", "Ready"].map((label, index) => (
          <span
            key={label}
            className={cn(
              "rounded-full px-2 py-1",
              index <= stepIndex ? "bg-primary/10 text-primary" : "text-muted-foreground",
            )}
          >
            {label}
          </span>
        ))}
      </div>

      {step === "welcome" ? (
        <div className="space-y-6 text-center">
          <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
            <MessageSquare className="size-6" />
          </div>
          <div className="space-y-2">
            <h1 className="text-hero font-semibold tracking-tight">{onboardingCopy.welcomeTitle}</h1>
            <p className="text-base font-medium text-foreground">{onboardingCopy.welcomeSubtitle}</p>
            <p className="text-sm text-muted-foreground">{onboardingCopy.welcomeBody}</p>
          </div>
          <Button type="button" size="lg" className="w-full" onClick={() => setStep("connect")}>
            {onboardingCopy.getStarted}
          </Button>
          <p className="text-xs text-muted-foreground">{onboardingCopy.welcomeTrust}</p>
        </div>
      ) : null}

      {step === "connect" ? (
        <div className="space-y-6 text-center">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold tracking-tight">{onboardingCopy.connectTitle}</h2>
            <p className="text-sm text-muted-foreground">{onboardingCopy.connectBody}</p>
            <p className="text-sm text-muted-foreground">{onboardingCopy.includeAll}</p>
          </div>

          {isConnected ? (
            <div className="flex items-center justify-center gap-2 text-sm text-success">
              <Loader2 className="size-4 animate-spin" />
              Drive connected — continuing…
            </div>
          ) : (
            <Button type="button" size="lg" className="w-full" onClick={handleConnect}>
              {onboardingCopy.connectCta}
            </Button>
          )}

          <p className="text-xs text-muted-foreground">
            Already connected?{" "}
            <button
              type="button"
              className="underline underline-offset-2"
              onClick={() => void refetchConnection()}
            >
              Check again
            </button>
          </p>
        </div>
      ) : null}

      {step === "prepare" ? (
        <div className="space-y-4">
          <PrepareKnowledgeView
            variant="embedded"
            autoStart
            onComplete={() => {
              void refreshKnowledge();
              setStep("ready");
            }}
          />
        </div>
      ) : null}

      {step === "ready" ? (
        <div className="space-y-6 text-center">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold tracking-tight">{onboardingCopy.readyTitle}</h2>
            <p className="text-sm text-muted-foreground">{onboardingCopy.readyBody}</p>
          </div>

          <div className="flex flex-col gap-2">
            {FIRST_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                className={buttonVariants({
                  variant: "outline",
                  className: "h-auto justify-start whitespace-normal px-4 py-3 text-left text-sm font-normal",
                })}
                onClick={() => finishOnboarding(question)}
              >
                {question}
              </button>
            ))}
          </div>

          <Button type="button" size="lg" className="w-full" onClick={() => finishOnboarding()}>
            {onboardingCopy.startChatting}
          </Button>
        </div>
      ) : null}

      {step !== "welcome" ? (
        <p className="text-center text-xs text-muted-foreground">
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => finishOnboarding()}
          >
            Skip for now
          </button>
        </p>
      ) : null}
    </div>
  );
}
