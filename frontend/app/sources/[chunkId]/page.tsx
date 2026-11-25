import { Suspense } from "react";
import { SourceView } from "@/components/sources/source-view";

export default function Page() {
  return <Suspense fallback={null}><SourceView /></Suspense>;
}
