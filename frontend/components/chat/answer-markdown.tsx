import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type AnswerMarkdownProps = {
  content: string;
};

export function AnswerMarkdown({ content }: AnswerMarkdownProps) {
  return (
    <div className="text-body-lg leading-relaxed text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ node, href, children, ...anchorProps }) {
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
