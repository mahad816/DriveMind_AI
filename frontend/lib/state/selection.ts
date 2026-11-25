/** Files chosen for preparation, in memory, for one owner. Survives navigation, refetches and tab switches;
 *  dropped with the owner's workspace. The five-document cap mirrors the queue's own limit (decision D4). */
export const SELECTION_LIMIT = 5;

export class SelectionStore {
  private ids: readonly string[] = [];
  private listeners = new Set<() => void>();
  getSnapshot = () => this.ids;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private set(ids: readonly string[]) { this.ids = ids; this.listeners.forEach(l => l()); }
  has = (id: string) => this.ids.includes(id);
  /** Returns false when the cap would be exceeded; nothing changes in that case. */
  toggle = (id: string): boolean => {
    if (this.ids.includes(id)) { this.set(this.ids.filter(v => v !== id)); return true; }
    if (this.ids.length >= SELECTION_LIMIT) return false;
    this.set([...this.ids, id]);
    return true;
  };
  remove = (id: string) => { if (this.ids.includes(id)) this.set(this.ids.filter(v => v !== id)); };
  /** Keep only ids still present and selectable after a refetch. */
  retain = (keep: (id: string) => boolean) => { const next = this.ids.filter(keep); if (next.length !== this.ids.length) this.set(next); };
  clear = () => { if (this.ids.length) this.set([]); };
}
