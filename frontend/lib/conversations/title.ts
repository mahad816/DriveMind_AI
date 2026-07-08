/** Derive a short, relevant sidebar title from the user's first message. */

const LEADING_PHRASE_RE =
  /^(?:please\s+)?(?:can you\s+)?(?:could you\s+)?(?:tell me about|what(?:'s| is)(?:\s+in|\s+inside)?|summarize|summary of|describe|explain|read|open|show me|content of|find|list|how many|count|check)\s+/i;

const TRAILING_PUNCT_RE = /[?.!]+$/;

/**
 * Build a ChatGPT-style conversation title from the first user message.
 *
 * Examples:
 * - `Tell me about "Far611"` → `Far611`
 * - `how many resume files do I have` → `Resume files`
 * - `What is LangGraph?` → `LangGraph`
 * - `hi` → `Hi`
 */
export function conversationTitleFromQuestion(question: string): string {
  const trimmed = question.trim();
  if (!trimmed) return "New chat";

  const quoted = trimmed.match(/"([^"]{1,80})"|'([^']{1,80})'/);
  if (quoted) {
    const name = (quoted[1] ?? quoted[2] ?? "").trim();
    if (name) return capLength(name);
  }

  let working = trimmed.replace(LEADING_PHRASE_RE, "").replace(TRAILING_PUNCT_RE, "").trim();

  // "how many resume files do I have" → focus on the subject
  const howMany = working.match(/^how many\s+(.+?)(?:\s+do i have|\s+are there|\s+in total)?$/i);
  if (howMany?.[1]) {
    working = howMany[1].trim();
  }

  // Drop trailing filler clauses
  working = working
    .replace(/\s+(do i have|are there|in total|in my drive|in google drive).*$/i, "")
    .trim();

  if (!working) {
    return capLength(trimmed);
  }

  // Short greetings keep natural casing
  if (/^(hi|hello|hey|thanks|thank you|ok|okay)$/i.test(working)) {
    return working.charAt(0).toUpperCase() + working.slice(1).toLowerCase();
  }

  const titled = working.charAt(0).toUpperCase() + working.slice(1);
  return capLength(titled);
}

function capLength(title: string, max = 48): string {
  if (title.length <= max) return title;
  return `${title.slice(0, max - 1)}…`;
}
