import { expect, it, vi } from "vitest";
import { SELECTION_LIMIT, SelectionStore } from "./selection";

it("caps the selection at five; the sixth toggle is refused and changes nothing", () => {
  const store = new SelectionStore();
  const listener = vi.fn(); store.subscribe(listener);
  for (let i = 1; i <= SELECTION_LIMIT; i++) expect(store.toggle(`f${i}`)).toBe(true);
  const before = store.getSnapshot();
  expect(store.toggle("f6")).toBe(false);
  expect(store.getSnapshot()).toBe(before);
  expect(listener).toHaveBeenCalledTimes(SELECTION_LIMIT);
});
it("toggling a selected file removes it, which makes room again", () => {
  const store = new SelectionStore();
  for (let i = 1; i <= 5; i++) store.toggle(`f${i}`);
  expect(store.toggle("f3")).toBe(true);
  expect(store.has("f3")).toBe(false);
  expect(store.toggle("f6")).toBe(true);
  expect(store.getSnapshot()).toEqual(["f1", "f2", "f4", "f5", "f6"]);
});
it("retain drops ids that are gone, and notifies only on a real change", () => {
  const store = new SelectionStore();
  store.toggle("a"); store.toggle("b");
  const listener = vi.fn(); store.subscribe(listener);
  store.retain(() => true); expect(listener).not.toHaveBeenCalled();
  store.retain(id => id !== "a"); expect(store.getSnapshot()).toEqual(["b"]); expect(listener).toHaveBeenCalledTimes(1);
  store.clear(); store.clear(); expect(listener).toHaveBeenCalledTimes(2);
});
