"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { PageShell } from "@/components/layout/page-shell";
import { SingleFilePreparationView } from "./single-file-preparation-view";
import { QueuePreparationView } from "./queue-preparation-view";
import { readPreparationGate } from "@/lib/knowledge/preparation-queue-store";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import { DEMO_MODE } from "@/lib/demo";

export function PreparationView() {
  const { userId } = useApplicationSession();
  const params = useSearchParams();
  return !DEMO_MODE && userId ? <OwnedPreparation key={`${userId}:${sessionRevision()}:${params.get("file") ?? "saved"}`} owner={userId} hasFile={params.has("file")} /> : null;
}
function OwnedPreparation({ owner, hasFile }: { owner: string; hasFile: boolean }) {
  const [kind, setKind] = useState("checking");
  useEffect(() => {
    const revision = sessionRevision();
    const inspect = () => {
      if (sessionOwner() !== owner || sessionRevision() !== revision) return;
      try { setKind(readPreparationGate(owner).kind); }
      catch { setKind("blocked"); }
    };
    inspect();
    window.addEventListener("storage", inspect);
    const timer = window.setInterval(inspect, 3000);
    return () => { clearInterval(timer); window.removeEventListener("storage", inspect); };
  }, [owner]);
  if (kind === "checking") return <p role="status" className="p-6">Checking preparation…</p>;
  if (kind === "legacy" || (kind === "empty" && hasFile)) return <SingleFilePreparationView />;
  return <PageShell title="Prepare documents" size="md"><QueuePreparationView owner={owner} /></PageShell>;
}
