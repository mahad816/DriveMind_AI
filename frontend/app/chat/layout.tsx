import { ChatWorkspace } from "@/components/chat/chat-workspace";

/** One chat workspace for /chat and /chat/[id], so creating a conversation never remounts the composer. */
export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return <><ChatWorkspace />{children}</>;
}
