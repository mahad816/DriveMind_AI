import { Suspense } from "react";
import { SettingsView } from "@/components/settings/settings-view";

export default function Page() {
  return <Suspense fallback={null}><SettingsView /></Suspense>;
}
