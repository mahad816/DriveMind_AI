"use client";
import { Dialog } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/controls";

const mac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** Only shortcuts that really exist are listed (see the key handlers in WorkspaceShell and Composer). */
export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const cmd = mac() ? "⌘" : "Ctrl";
  const rows: { keys: string[]; what: string }[] = [
    { keys: [cmd, "K"], what: "Search conversations, file names and actions" },
    { keys: ["/"], what: "Search, when you are not typing" },
    { keys: [mac() ? "⇧⌘O" : "Ctrl", ...(mac() ? [] : ["Shift", "O"])], what: "Start a new chat" },
    { keys: ["Enter"], what: "Send the question" },
    { keys: ["Shift", "Enter"], what: "New line in the question" },
    { keys: ["Esc"], what: "Close a panel or dialog" },
    { keys: ["?"], what: "Show this list" },
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts">
      <dl className="mt-3 divide-y divide-rule">
        {rows.map(row => (
          <div key={row.what} className="flex items-center justify-between gap-6 py-2.5">
            <dt className="text-label text-graphite">{row.what}</dt>
            <dd className="flex shrink-0 items-center gap-1">{row.keys.map(k => <Kbd key={k}>{k}</Kbd>)}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
