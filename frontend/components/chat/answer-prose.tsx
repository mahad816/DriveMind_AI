"use client";
import { createContext, memo, useContext } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Root } from "mdast";
import { splitCitationText } from "@/lib/chat/citations";
import { cn } from "@/lib/utils";

/** Per-answer link between markers and their evidence notes. */
export type EvidenceLink = {
  turnId: string;
  active: number | null;
  setActive: (n: number | null) => void;
  open: (n: number) => void;
  count: number;
};
export const EvidenceContext = createContext<EvidenceLink | null>(null);
export const noteId = (turnId: string, n: number) => `note-${turnId}-${n}`;

type Node = { type: string; value?: string; children?: Node[]; url?: string; data?: { hProperties: Record<string, string> } };
function markCitations(node: Node, count: number) {
  if (!node.children || ["link", "linkReference", "image", "imageReference", "code", "inlineCode"].includes(node.type)) return;
  node.children = node.children.flatMap(child => child.type !== "text" || typeof child.value !== "string" ? [child]
    : splitCitationText(child.value, count).map((part): Node => part.kind === "text" ? { type: "text", value: part.value }
      : { type: "link", url: `#cite-${part.number}`, children: [{ type: "text", value: String(part.number) }], data: { hProperties: { "data-citation": String(part.number) } } }));
  for (const child of node.children) markCitations(child, count);
}

export const AnswerProse = memo(function AnswerProse({ text, count, provisional }: { text: string; count: number; provisional?: boolean }) {
  return (
    <div className={cn("prose-answer prose-settle", provisional && "prose-provisional")}>
      <ReactMarkdown remarkPlugins={[remarkGfm, () => (tree: Root) => markCitations(tree as unknown as Node, count)]}
        components={{
          a({ node, href, children, ...props }) {
            const n = Number(node?.properties?.dataCitation ?? node?.properties?.["data-citation"]);
            if (Number.isInteger(n) && href === `#cite-${n}`) return <CitationMarker n={n} />;
            const external = href?.startsWith("http");
            return <a {...props} href={href} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>{children}</a>;
          },
          table({ children }) { return <div className="table-wrap"><table>{children}</table></div>; },
        }}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

export function CitationMarker({ n }: { n: number }) {
  const link = useContext(EvidenceContext);
  const active = link?.active === n;
  return (
    <button type="button" data-citation={n}
      aria-label={`Source ${n}`} aria-describedby={link ? noteId(link.turnId, n) : undefined}
      onMouseEnter={() => link?.setActive(n)} onMouseLeave={() => link?.setActive(null)}
      onFocus={() => link?.setActive(n)} onBlur={() => link?.setActive(null)}
      onClick={() => link?.open(n)}
      className={cn("hit mx-[0.12em] inline-grid h-[1.2rem] min-w-[1.2rem] translate-y-[-0.1em] place-items-center rounded-[5px] px-1 align-middle font-sans text-[0.6875rem] font-semibold tabular leading-none",
        "transition-colors duration-[120ms]",
        active ? "bg-highlight text-ink ring-1 ring-highlight-edge/50" : "bg-archive-wash text-archive-text hover:bg-highlight hover:text-ink")}>
      {n}
    </button>
  );
}
