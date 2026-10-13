"use client";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useToast } from "@/components/ui/toast-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { consumeOnboardingOAuthPending } from "@/lib/onboarding/storage";
/** Callback hints never establish identity; only backend session inspection does. */
export function useOAuthSettingsCallback() {
  const router = useRouter();
  const params = useSearchParams();
  const { pushToast } = useToast();
  const { refresh } = useApplicationSession();
  useEffect(() => {
    if (!params.has("login") && !params.has("connected") && !params.has("email") && !params.has("error")) return;
    let live = true;
    void refresh().then(verified => {
      if (!live) return;
      if (verified && params.get("login") === "success") {
        pushToast({ title: "Application session verified", variant: "success" });
      }
      const onboarding = consumeOnboardingOAuthPending();
      router.replace(verified && onboarding ? "/onboarding" : "/settings");
    });
    return () => { live = false; };
  }, [params, pushToast, refresh, router]);
}
