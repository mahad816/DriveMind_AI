import { cn } from "@/lib/utils";

type SettingsSectionProps = {
  title: string;
  children: React.ReactNode;
  className?: string;
};

export function SettingsSection({ title, children, className }: SettingsSectionProps) {
  const headingId = `settings-${title.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <section className={cn("space-y-4 border-b border-border pb-8", className)} aria-labelledby={headingId}>
      <h2 id={headingId} className="text-sm font-semibold text-foreground">
        {title}
      </h2>
      <div>{children}</div>
    </section>
  );
}
