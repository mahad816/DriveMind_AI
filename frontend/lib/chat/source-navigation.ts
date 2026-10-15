const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Navigation context only; the conversation endpoint still authorizes access. */
export function conversationHref(origin?: string | null): string {
  return origin && UUID.test(origin) ? `/chat/${origin.toLowerCase()}` : "/chat";
}

export function sourceHref(chunkId: string, origin?: string | null): string {
  const conversation = conversationHref(origin);
  return `/sources/${encodeURIComponent(chunkId)}${conversation === "/chat" ? "" : `?conversation=${conversation.slice(6)}`}`;
}
