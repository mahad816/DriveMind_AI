"use client";
import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import { DEMO_MODE } from "@/lib/demo";
import { EMPTY_SERVER_CONVERSATIONS, ServerConversationController } from "@/lib/conversations/server-controller";
import type { ConversationTransport, ServerConversationState } from "@/lib/conversations/server-controller";
type ContextValue = {
  state: ServerConversationState;
  controller: ServerConversationController;
};
const Context = createContext<ContextValue | null>(null);
/** S3C must mount ONE provider under ApplicationSessionProvider for chat/sidebar. */
function NormalServerConversationsProvider({ children, transport }: {
  children: ReactNode;
  transport?: ConversationTransport;
}) {
  const session = useApplicationSession();
  const [controller] = useState(() => new ServerConversationController(transport));
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
  return <Context.Provider value={{ state: visible ? state : EMPTY_SERVER_CONVERSATIONS, controller }}>{children}</Context.Provider>;
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
