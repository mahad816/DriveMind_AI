/**
 * Locate a cited snippet inside its full source passage. Only an actual occurrence is returned (whitespace may differ,
 * and a trailing ellipsis added by the backend is ignored); anything less is "not found" and nothing is highlighted.
 * Highlights are never inferred, fuzzily matched or invented.
 */
export type PassageParts = { before: string; match: string; after: string } | null;

const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
export function locateSnippet(text: string, snippet: string): PassageParts {
  const cleaned = snippet.trim().replace(/^(…|\.\.\.)\s*/, "").replace(/\s*(…|\.\.\.)$/, "");
  const tokens = cleaned.split(/\s+/).filter(Boolean);
  if (tokens.length < 3) return null; // too short to locate unambiguously
  const pattern = new RegExp(tokens.map(escape).join("\\s+"));
  const found = pattern.exec(text);
  if (!found) return null;
  return { before: text.slice(0, found.index), match: found[0], after: text.slice(found.index + found[0].length) };
}

/** Plain-text copy of an answer: markers removed, cited files listed by name. */
export function answerForClipboard(answer: string, filenames: string[]): string {
  const body = answer.replace(/\s?\[(\d+)\]/g, "").trim();
  const unique = [...new Set(filenames)];
  return unique.length ? `${body}\n\nSources:\n${unique.map(name => `- ${name}`).join("\n")}` : body;
}
