import { Suspense } from "react";

import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { Skeleton } from "@/components/ui/skeleton";

export default function OnboardingPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto flex max-w-lg flex-col gap-4 px-4 py-16">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-24 w-full" />
        </div>
      }
    >
      <OnboardingFlow />
    </Suspense>
  );
}
