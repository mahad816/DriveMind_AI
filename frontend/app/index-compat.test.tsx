import { beforeEach, expect, it, vi } from "vitest";
import IndexPage from "./(main)/index/page";
import { redirect } from "next/navigation";
import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("next/navigation", () => ({ redirect: vi.fn((url: string) => { throw new Error(`redirect:${url}`); }) }));
beforeEach(() => { mode.demo = false; vi.clearAllMocks(); });
it("legacy normal /index redirects to Files without rendering preparation", () => {
  expect(() => IndexPage()).toThrow("redirect:/files"); expect(redirect).toHaveBeenCalledExactlyOnceWith("/files");
});
it("HarborDesk retains its existing Knowledge page", () => {
  mode.demo = true; expect(IndexPage().type).toBe(PrepareKnowledgeView); expect(redirect).not.toHaveBeenCalled();
});
