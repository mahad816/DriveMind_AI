"use client";

import { forwardRef } from "react";

import {
  ChatComposer,
  type ChatComposerHandle,
} from "@/components/chat/chat-composer";
import { ComposerShortcutHint } from "@/components/chat/message-action-bar";
import { cn } from "@/lib/utils";

type ComposerDockProps = {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  isLoading: boolean;
  className?: string;
};

export const ComposerDock = forwardRef<ChatComposerHandle, ComposerDockProps>(
  function ComposerDock(
    { value, onChange, onSubmit, disabled, isLoading, className },
    ref,
  ) {
    return (
      <div
        className={cn(
          "shrink-0 bg-gradient-to-t from-surface-canvas via-surface-canvas to-transparent px-0 pb-2 pt-4",
          className,
        )}
      >
        <ChatComposer
          ref={ref}
          value={value}
          onChange={onChange}
          onSubmit={onSubmit}
          disabled={disabled}
          isLoading={isLoading}
        />
        <ComposerShortcutHint className="mt-2 hidden sm:block" />
      </div>
    );
  },
);
