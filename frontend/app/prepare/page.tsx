import { Suspense } from "react";
import { redirect } from "next/navigation";
import { DEMO_MODE } from "@/lib/demo";
import { SingleFilePreparationView } from "@/components/knowledge/single-file-preparation-view";

export default function PreparePage() {
  if (DEMO_MODE) redirect("/index");
  return <Suspense fallback={<p role="status" className="p-6">Checking preparation…</p>}><SingleFilePreparationView /></Suspense>;
}
