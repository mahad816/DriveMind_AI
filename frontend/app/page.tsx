import { OnboardingAwareHomeRedirect } from "@/components/onboarding/onboarding-gate";
import { DemoHomeRedirect } from "@/components/onboarding/demo-home-redirect";
import { DEMO_MODE } from "@/lib/demo";

export default function HomePage() {
  if (DEMO_MODE) {
    return <DemoHomeRedirect />;
  }
  return <OnboardingAwareHomeRedirect />;
}
