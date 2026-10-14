"use client";

import { DEMO_MODE } from "@/lib/demo";
import { DemoChatInterface } from "@/components/chat/demo-chat-interface";
import { ServerChatInterface } from "@/components/chat/server-chat-interface";

/** The demo's browser history never enters the authenticated server controller. */
export function ChatInterface(props: { conversationId?: string }) {
  return DEMO_MODE ? <DemoChatInterface {...props} /> : <ServerChatInterface {...props} />;
}
