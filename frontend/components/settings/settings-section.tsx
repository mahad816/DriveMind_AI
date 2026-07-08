import { cn } from "@/lib/utils";

type SettingsSectionProps = {
  title: string;
  children: React.ReactNode;
  className?: string;
};

export function SettingsSection({ title, children, className }: SettingsSectionProps) {
  const headingId = `settings-${title.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <section className={cn("space-y-3", className)} aria-labelledby={headingId}>
      <h2 id={headingId} className="text-sm font-medium text-foreground">
        {title}
      </h2>
      <div className="rounded-2xl border border-border bg-surface-elevated p-4">{children}</div>
    </section>
  );
}
