"use client";
import type { ReactNode } from "react";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { ServerConversationsProvider } from "@/components/providers/server-conversations-provider";
import { WorkspaceProvider } from "@/components/workspace/workspace-provider";
import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { DemoRoot } from "@/components/demo/demo-root";
import { DEMO_MODE } from "@/lib/demo";

/** Rendered only once the session boundary has a verified owner (the boundary keys this subtree by owner). */
export function WorkspaceRoot({ children }: { children: ReactNode }) {
  const session = useApplicationSession();
  // Public demo: the fictional sample library, no sign-in (backend DEMO_MODE serves these routes anonymously).
  if (DEMO_MODE) return <DemoRoot />;
  if (!session.userId) return null;
  return (
    <ServerConversationsProvider>
      <WorkspaceProvider owner={session.userId}>
        <WorkspaceShell>{children}</WorkspaceShell>
      </WorkspaceProvider>
    </ServerConversationsProvider>
  );
}
