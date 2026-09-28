import type { Root } from "mdast";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationPreview } from "@/components/chat/citation-preview";
import type { CitationItem } from "@/lib/api/types";
import { splitCitationText } from "@/lib/chat/citations";

type AnswerMarkdownProps = {
  content: string;
  citations?: CitationItem[];
  onSourceSelect?: (citation: CitationItem, citations: CitationItem[]) => void;
};

type MarkdownNode = {
  type: string;
  value?: string;
  children?: MarkdownNode[];
  url?: string;
  data?: { hProperties: Record<string, string> };
};

function addCitationLinks(node: MarkdownNode, citationCount: number): void {
  if (
    !node.children ||
    node.type === "link" ||
    node.type === "linkReference" ||
    node.type === "image" ||
    node.type === "imageReference"
  ) {
    return;
  }

  node.children = node.children.flatMap((child) => {
    if (child.type !== "text" || typeof child.value !== "string") return [child];
    return splitCitationText(child.value, citationCount).map((part): MarkdownNode =>
      part.kind === "text"
        ? { type: "text", value: part.value }
        : {
            type: "link",
            url: `#drivemind-citation-${part.number}`,
            children: [{ type: "text", value: `[${part.number}]` }],
            data: { hProperties: { "data-citation-number": String(part.number) } },
          },
    );
  });
  for (const child of node.children) addCitationLinks(child, citationCount);
}

export function AnswerMarkdown({ content, citations = [], onSourceSelect }: AnswerMarkdownProps) {
  return (
    <div className="text-body-lg leading-relaxed text-foreground">
      <ReactMarkdown
        remarkPlugins={[
          remarkGfm,
          () => (tree: Root) => addCitationLinks(tree as unknown as MarkdownNode, citations.length),
        ]}
        components={{
          a({ node, href, children, ...anchorProps }) {
            const marker = node?.properties?.["data-citation-number"];
            const number = typeof marker === "string" ? Number(marker) : NaN;
            const citation = citations[number - 1];
            if (citation && href === `#drivemind-citation-${number}`) {
              return (
                <CitationPreview
                  citation={citation}
                  number={number}
                  onOpenEvidence={
                    onSourceSelect ? (selected) => onSourceSelect(selected, citations) : undefined
                  }
                />
              );
            }
            void node;
            const isExternal = href?.startsWith("http") ?? false;
            return (
              <a
                {...anchorProps}
                href={href}
                target={isExternal ? "_blank" : undefined}
                rel={isExternal ? "noreferrer" : undefined}
                className="font-medium text-primary underline underline-offset-4 hover:text-primary/80"
              >
                {children}
              </a>
            );
          },
          code({ children, className }) {
            return (
              <code
                className={
                  className ??
                  "rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.9em] text-foreground"
                }
              >
                {children}
              </code>
            );
          },
          pre({ children }) {
            return (
              <pre className="mb-4 overflow-x-auto rounded-xl border border-border bg-muted/60 p-4 text-sm last:mb-0">
                {children}
              </pre>
            );
          },
          p({ children }) {
            return <p className="mb-4 last:mb-0">{children}</p>;
          },
          h1({ children }) {
            return <h1 className="mb-3 text-xl font-semibold">{children}</h1>;
          },
          h2({ children }) {
            return <h2 className="mb-2 text-lg font-semibold">{children}</h2>;
          },
          h3({ children }) {
            return <h3 className="mb-2 text-base font-semibold">{children}</h3>;
          },
          h4({ children }) {
            return <h4 className="mb-2 text-base font-semibold">{children}</h4>;
          },
          ul({ children }) {
            return <ul className="mb-4 list-disc space-y-1.5 pl-5 last:mb-0">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="mb-4 list-decimal space-y-1.5 pl-5 last:mb-0">{children}</ol>;
          },
          blockquote({ children }) {
            return (
              <blockquote className="mb-4 border-l-2 border-primary/30 pl-4 text-muted-foreground last:mb-0">
                {children}
              </blockquote>
            );
          },
          hr() {
            return <hr className="my-4 border-border" />;
          },
          table({ children }) {
            return (
              <div
                role="region"
                aria-label="Answer table"
                tabIndex={0}
                className="mb-4 overflow-x-auto last:mb-0"
              >
                <table className="w-full border-collapse text-left text-sm">{children}</table>
              </div>
            );
          },
          th({ children }) {
            return <th className="border-b border-border px-3 py-2 font-semibold">{children}</th>;
          },
          td({ children }) {
            return <td className="border-b border-border px-3 py-2 align-top">{children}</td>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
