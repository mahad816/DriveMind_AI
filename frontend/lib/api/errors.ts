/** Typed API errors surfaced from FastAPI responses. */
import { DEMO_MODE } from "@/lib/demo";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly body: unknown;

  constructor(status: number, detail: string, body?: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function chatErrorMessage(error: unknown): string {
  if (!DEMO_MODE) {
    return isApiError(error) ? error.detail : error instanceof Error ? error.message : "Request failed";
  }
  if (isApiError(error)) {
    if (error.status === 413) return "Your message is too large for the public demo. Please shorten it and try again.";
    if (error.status === 429) return "The public demo is busy right now. Please try again shortly.";
    if (error.status === 422) {
      if (/question/i.test(error.detail) && /limit|too long/i.test(error.detail)) {
        return "Your message is too long. Please keep it under 4,000 characters.";
      }
      return "Please check your message and try again.";
    }
    if (error.status === 503) return "The sample knowledge base is temporarily unavailable. Please try again shortly.";
  }
  return "Something went wrong while answering. Please try again.";
}
