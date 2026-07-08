import { describe, expect, it } from "vitest";

import { conversationTitleFromQuestion } from "@/lib/conversations/title";

describe("conversationTitleFromQuestion", () => {
  it("uses quoted file names", () => {
    expect(conversationTitleFromQuestion('Tell me about "Far611"')).toBe("Far611");
    expect(conversationTitleFromQuestion("what is in 'resume.pdf'")).toBe("resume.pdf");
  });

  it("strips leading question phrases", () => {
    expect(conversationTitleFromQuestion("What is LangGraph?")).toBe("LangGraph");
    expect(conversationTitleFromQuestion("Summarize my meeting notes")).toBe("My meeting notes");
  });

  it("focuses how-many questions on the subject", () => {
    expect(conversationTitleFromQuestion("how many resume files do I have")).toBe("Resume files");
  });

  it("handles short greetings", () => {
    expect(conversationTitleFromQuestion("hi")).toBe("Hi");
    expect(conversationTitleFromQuestion("hello")).toBe("Hello");
  });

  it("truncates long titles", () => {
    const long = "a".repeat(60);
    expect(conversationTitleFromQuestion(long)).toHaveLength(48);
    expect(conversationTitleFromQuestion(long).endsWith("…")).toBe(true);
  });
});
