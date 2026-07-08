import type { CitationItem } from "@/lib/api/types";

const MAX_SUGGESTIONS = 3;

/** Context-aware follow-up prompts shown after the latest answer. */
export function buildFollowUpSuggestions(
  question: string,
  answer: string,
  citations: CitationItem[],
): string[] {
  const suggestions: string[] = [];
  const topFile = citations[0]?.filename?.trim();

  if (topFile) {
    suggestions.push(`What else is in "${topFile}"?`);
  }

  if (citations.length > 1) {
    suggestions.push("Which source had the strongest evidence?");
  }

  if (answer.length > 400) {
    suggestions.push("Summarize that in 3 bullet points");
  } else {
    suggestions.push("Can you elaborate on that?");
  }

  if (/how many|count|list/i.test(question)) {
    suggestions.push("Show me the most relevant file names");
  }

  const unique = [...new Set(suggestions.map((s) => s.trim()).filter(Boolean))];
  return unique.slice(0, MAX_SUGGESTIONS);
}
