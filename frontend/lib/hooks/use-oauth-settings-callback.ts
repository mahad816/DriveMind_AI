"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useToast } from "@/components/ui/toast-provider";
import { consumeOnboardingOAuthPending } from "@/lib/onboarding/storage";
import { clearConnectedEmail, setConnectedEmail } from "@/lib/settings/storage";
import { settingsCopy } from "@/lib/user-language";

export function useOAuthSettingsCallback() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { pushToast } = useToast();

  useEffect(() => {
    const connected = searchParams.get("connected");
    const email = searchParams.get("email");
    const error = searchParams.get("error");

    if (!connected && !error) {
      return;
    }

    if (connected === "true") {
      if (email) {
        setConnectedEmail(email);
      }
      pushToast({
        title: settingsCopy.driveConnectedToast,
        description: settingsCopy.driveConnectedHint,
        variant: "success",
      });
    } else if (error) {
      pushToast({
        title: settingsCopy.driveErrorToast,
        description: error,
        variant: "error",
      });
    }

    if (consumeOnboardingOAuthPending()) {
      router.replace("/onboarding?step=prepare");
      return;
    }

    router.replace("/settings");
  }, [pushToast, router, searchParams]);
}

export function handleDisconnectDrive() {
  clearConnectedEmail();
  window.open("https://myaccount.google.com/permissions", "_blank", "noopener,noreferrer");
}
