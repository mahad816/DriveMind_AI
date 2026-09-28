import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatComposer } from "@/components/chat/chat-composer";

afterEach(cleanup);

function composer(value: string, options: { disabled?: boolean; isLoading?: boolean } = {}) {
  const onSubmit = vi.fn();
  const onChange = vi.fn();
  render(
    <ChatComposer
      value={value}
      onChange={onChange}
      onSubmit={onSubmit}
      disabled={options.disabled ?? false}
      isLoading={options.isLoading ?? false}
    />,
  );
  return { onSubmit, onChange, input: screen.getByRole("textbox", { name: "Message" }) };
}

describe("chat composer input", () => {
  it("submits nonempty text with Enter and leaves Shift+Enter for a newline", () => {
    const { onSubmit, input } = composer("Find the itinerary");
    expect(fireEvent.keyDown(input, { key: "Enter", shiftKey: true })).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not submit the Enter used to confirm IME composition, then allows Enter afterward", () => {
    const { onSubmit, input } = composer("会議");
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not submit whitespace or blocked and pending requests", () => {
    const { onSubmit, input } = composer("   ");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    cleanup();

    const blocked = composer("Ready", { disabled: true });
    expect(blocked.input).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    cleanup();

    const pending = composer("Ready", { isLoading: true });
    fireEvent.keyDown(pending.input, { key: "Enter" });
    expect(pending.onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sending message" })).toBeDisabled();
  });

  it("has one send control without unsupported attachment, microphone, model, or tools controls", () => {
    composer("Ready");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled();
  });
});
