/**
 * Stale-while-revalidate read model for one owner (decision D3: no query library).
 *
 * - One instance per verified owner: the workspace subtree is keyed by owner, so an account change drops every cache.
 * - Concurrent loads share one request; a forced refresh queued behind an in-flight load runs after it, so a
 *   post-mutation refresh never settles on a pre-mutation response.
 * - Data already shown stays shown while refreshing and after a failed refresh (with the error beside it).
 * - Never polls by itself. Callers decide when to read (mount, visibility return, after a mutation).
 */
export type ResourceState<T> = Readonly<{
  data: T | null;
  error: unknown;
  /** True only while the first load has no data to show. Refreshes never set it. */
  loading: boolean;
  refreshing: boolean;
  updatedAt: number | null;
}>;

export class Resource<T> {
  private state: ResourceState<T> = { data: null, error: null, loading: false, refreshing: false, updatedAt: null };
  private listeners = new Set<() => void>();
  private inFlight: Promise<void> | null = null;
  private queued: Promise<void> | null = null;
  private controller: AbortController | null = null;

  constructor(private readonly fetcher: (signal: AbortSignal) => Promise<T>, private readonly now: () => number = Date.now) {}

  getSnapshot = (): ResourceState<T> => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };

  private publish(patch: Partial<ResourceState<T>>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach(listener => listener());
  }

  /** Loads unless the data is younger than maxAgeMs. Joins a load already in flight. */
  load = (maxAgeMs = 0): Promise<void> => {
    if (this.inFlight) return this.inFlight;
    if (maxAgeMs > 0 && this.state.updatedAt !== null && this.now() - this.state.updatedAt < maxAgeMs && !this.state.error) return Promise.resolve();
    return this.run();
  };

  /** Always reads again; if a load is in flight, runs once more after it. */
  refresh = (): Promise<void> => {
    if (!this.inFlight) return this.run();
    if (!this.queued) this.queued = this.inFlight.then(() => this.run()).finally(() => { this.queued = null; });
    return this.queued;
  };

  isStale = (maxAgeMs: number) => this.state.updatedAt === null || this.now() - this.state.updatedAt >= maxAgeMs;

  private run(): Promise<void> {
    const controller = new AbortController();
    this.controller = controller;
    this.publish(this.state.data === null ? { loading: true } : { refreshing: true });
    const run = (async () => {
      try {
        const data = await this.fetcher(controller.signal);
        if (!controller.signal.aborted) this.publish({ data, error: null, loading: false, refreshing: false, updatedAt: this.now() });
      } catch (error) {
        if (!controller.signal.aborted) this.publish({ error, loading: false, refreshing: false });
      }
    })().finally(() => { if (this.inFlight === run) this.inFlight = null; });
    this.inFlight = run;
    return run;
  }

  /** Kept for symmetry with the controllers; dispose never blocks later loads (React Strict Mode re-runs effects
   *  on the same instance, children before parents). */
  connect = () => {};
  /** Abandons the request in flight; its late result is ignored. */
  dispose = () => { this.controller?.abort(); this.controller = null; this.inFlight = null; this.queued = null;
    if (this.state.loading || this.state.refreshing) this.state = { ...this.state, loading: false, refreshing: false }; };
}
