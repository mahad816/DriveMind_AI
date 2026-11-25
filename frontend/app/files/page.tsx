import { Suspense } from "react";
import { LibraryView } from "@/components/library/library-view";

export default function Page() {
  return <Suspense fallback={null}><LibraryView /></Suspense>;
}
