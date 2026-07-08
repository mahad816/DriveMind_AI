"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { hasCompletedOnboarding } from "@/lib/onboarding/storage";

type OnboardingGateProps = {
  children: React.ReactNode;
};

const BYPASS_PREFIXES = ["/onboarding", "/settings", "/index", "/prepare", "/sources"];

export function OnboardingGate({ children }: OnboardingGateProps) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (BYPASS_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
      return;
    }
    if (!hasCompletedOnboarding()) {
      router.replace("/onboarding");
    }
  }, [pathname, router]);

  return children;
}

export function OnboardingAwareHomeRedirect() {
  const router = useRouter();

  useEffect(() => {
    if (!hasCompletedOnboarding()) {
      router.replace("/onboarding");
      return;
    }
    router.replace("/chat");
  }, [router]);

  return null;
}
