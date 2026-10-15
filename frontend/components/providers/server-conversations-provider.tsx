"use client";
import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { sessionOwner, sessionRevision, SESSION_REQUESTS_INVALIDATED_EVENT } from "@/lib/api/session-events";
import { CreationDraftHandoff } from "@/lib/conversations/creation-draft-handoff";
import { DEMO_MODE } from "@/lib/demo";
import { EMPTY_SERVER_CONVERSATIONS, ServerConversationController } from "@/lib/conversations/server-controller";
import type { ConversationTransport, ServerConversationState } from "@/lib/conversations/server-controller";
type ContextValue = {
  state: ServerConversationState;
  controller: ServerConversationController;
  creationDraft: CreationDraftHandoff;
};
const Context = createContext<ContextValue | null>(null);
/** S3C must mount ONE provider under ApplicationSessionProvider for chat/sidebar. */
function NormalServerConversationsProvider({ children, transport }: {
  children: ReactNode;
  transport?: ConversationTransport;
}) {
  const session = useApplicationSession();
  const [controller] = useState(() => new ServerConversationController(transport));
  const [creationDraft] = useState(() => new CreationDraftHandoff());
  const pathname = usePathname();
  useEffect(() => {
    window.addEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, creationDraft.clear);
    return () => {
      window.removeEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, creationDraft.clear);
      creationDraft.clear();
    };
  }, [creationDraft]);
  useEffect(() => { creationDraft.navigate(pathname); }, [creationDraft, pathname]);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, () => EMPTY_SERVER_CONVERSATIONS);
  useEffect(() => { controller.connect(); return () => controller.dispose(); }, [controller]);
  useEffect(() => {
    if (!DEMO_MODE && session.status === "ready" && session.userId === sessionOwner()) {
      const current = controller.getSnapshot();
      if (current.ownerId !== session.userId || current.sessionRevision !== sessionRevision())
        void controller.initialize();
    }
    else
      controller.reset();
  }, [controller, session.status, session.userId, state.sessionRevision]);
  const visible = !DEMO_MODE && session.status === "ready" && state.ownerId === session.userId
    && state.ownerId === sessionOwner() && state.sessionRevision === sessionRevision();
  useEffect(() => { if (!visible) creationDraft.clear(); }, [creationDraft, visible]);
  return <Context.Provider value={{ state: visible ? state : EMPTY_SERVER_CONVERSATIONS, controller, creationDraft }}>{children}</Context.Provider>;
}
export function ServerConversationsProvider(props: {
  children: ReactNode;
  transport?: ConversationTransport;
}) {
  return DEMO_MODE ? <>{props.children}</> : <NormalServerConversationsProvider {...props}/>;
}
export function useServerConversations(): ContextValue {
  const value = useContext(Context);
  if (!value)
    throw new Error("ServerConversationsProvider is required");
  return value;
}
