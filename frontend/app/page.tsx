import { redirect } from "next/navigation";
import { OnboardingAwareHomeRedirect } from "@/components/onboarding/onboarding-gate";
import { DEMO_MODE } from "@/lib/demo";

type HomeProps = { searchParams?: Promise<Record<string, string | string[] | undefined>> };

export default async function HomePage({ searchParams }: HomeProps) {
  if (DEMO_MODE) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(await searchParams ?? {})) {
      if (Array.isArray(value)) value.forEach((item) => query.append(key, item));
      else if (value !== undefined) query.set(key, value);
    }
    redirect(`/chat${query.size ? `?${query}` : ""}`);
  }
  return <OnboardingAwareHomeRedirect />;
}
