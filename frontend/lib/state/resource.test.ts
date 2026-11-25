import { describe, expect, it, vi } from "vitest";
import { Resource } from "./resource";

const deferred = <T,>() => { let resolve!: (v: T) => void, reject!: (e: unknown) => void; const promise = new Promise<T>((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

describe("Resource", () => {
  it("shares one request between concurrent loads", async () => {
    const fetcher = vi.fn().mockResolvedValue([1]);
    const r = new Resource(fetcher);
    await Promise.all([r.load(), r.load(), r.load()]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(r.getSnapshot().data).toEqual([1]);
  });
  it("skips a load while data is fresh and reloads once stale", async () => {
    let now = 1000;
    const fetcher = vi.fn().mockResolvedValue("x");
    const r = new Resource(fetcher, () => now);
    await r.load(30_000); now += 10_000; await r.load(30_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    now += 30_000; await r.load(30_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("keeps shown data during and after a failed refresh, and never re-enters first-load state", async () => {
    const second = deferred<string>();
    const fetcher = vi.fn().mockResolvedValueOnce("first").mockReturnValueOnce(second.promise);
    const r = new Resource(fetcher);
    await r.load();
    const pending = r.refresh();
    expect(r.getSnapshot()).toMatchObject({ data: "first", loading: false, refreshing: true });
    second.reject(new Error("down")); await pending;
    expect(r.getSnapshot()).toMatchObject({ data: "first", loading: false, refreshing: false });
    expect(r.getSnapshot().error).toBeInstanceOf(Error);
  });
  it("a refresh requested during a load runs after it, so a post-mutation read is never the old one", async () => {
    const first = deferred<string>();
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce("after");
    const r = new Resource(fetcher);
    const a = r.load(); const b = r.refresh();
    first.resolve("before"); await a; await b;
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(r.getSnapshot().data).toBe("after");
  });
  it("publishes nothing after dispose", async () => {
    const pending = deferred<string>();
    const r = new Resource(() => pending.promise);
    const listener = vi.fn(); r.subscribe(listener);
    const load = r.load(); listener.mockClear(); r.dispose();
    pending.resolve("late"); await load;
    expect(listener).not.toHaveBeenCalled();
    expect(r.getSnapshot().data).toBeNull();
  });
});
