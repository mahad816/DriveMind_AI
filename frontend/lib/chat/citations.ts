export type CitationTextPart =
  | { kind: "text"; value: string }
  | { kind: "citation"; number: number };

/** Split only valid, one-based citation markers; leave all other text intact. */
export function splitCitationText(value: string, citationCount: number): CitationTextPart[] {
  const parts: CitationTextPart[] = [];
  let start = 0;

  for (const match of value.matchAll(/\[([1-9]\d*)\]/g)) {
    const number = Number(match[1]);
    if (!Number.isSafeInteger(number) || number > citationCount) continue;
    const index = match.index ?? 0;
    if (index > start) parts.push({ kind: "text", value: value.slice(start, index) });
    parts.push({ kind: "citation", number });
    start = index + match[0].length;
  }

  if (start < value.length) parts.push({ kind: "text", value: value.slice(start) });
  return parts;
}
