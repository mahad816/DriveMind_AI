import { Suspense } from "react";
import { WelcomeView } from "@/components/setup/welcome-view";

export default function Page() {
  return <Suspense fallback={null}><WelcomeView /></Suspense>;
}
