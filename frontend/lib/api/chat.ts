import { apiFetch } from "@/lib/api/client";
import type { ChatRequest, ChatResponse } from "@/lib/api/types";

export async function askQuestion(payload: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
