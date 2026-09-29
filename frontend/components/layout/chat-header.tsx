type ChatHeaderProps = {
  title: string | null;
};

/** Chat chrome only; conversation data stays owned by the existing conversation hook. */
export function ChatHeader({ title }: ChatHeaderProps) {
  if (!title) return null;

  return (
    <header className="hidden h-14 shrink-0 items-center border-b border-border bg-background px-6 md:flex">
      <p className="min-w-0 truncate text-sm font-medium tracking-tight text-foreground">{title}</p>
    </header>
  );
}
