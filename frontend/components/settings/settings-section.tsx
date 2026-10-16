import { cn } from "@/lib/utils";
import { DEMO_MODE } from "@/lib/demo";

type SettingsSectionProps = {
  title: string;
  children: React.ReactNode;
  className?: string;
};

export function SettingsSection({ title, children, className }: SettingsSectionProps) {
  const headingId = `settings-${title.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <section className={cn("border-b border-border", DEMO_MODE ? "space-y-4 pb-8" : "space-y-3 pb-6", className)} aria-labelledby={headingId}>
      <h2 id={headingId} className={cn("font-semibold text-foreground", DEMO_MODE ? "text-sm" : "text-base")}>
        {title}
      </h2>
      <div>{children}</div>
    </section>
  );
}
