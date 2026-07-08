import { ChatComposer } from "@/components/chat/chat-composer";
import { cn } from "@/lib/utils";

type ComposerDockProps = {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  isLoading: boolean;
  className?: string;
};

export function ComposerDock({
  value,
  onChange,
  onSubmit,
  disabled,
  isLoading,
  className,
}: ComposerDockProps) {
  return (
    <div
      className={cn(
        "shrink-0 bg-gradient-to-t from-surface-canvas via-surface-canvas to-transparent px-0 pb-1 pt-4",
        className,
      )}
    >
      <ChatComposer
        value={value}
        onChange={onChange}
        onSubmit={onSubmit}
        disabled={disabled}
        isLoading={isLoading}
      />
    </div>
  );
}
