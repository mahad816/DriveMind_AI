/** Normal-mode memory only. The shared provider in S3C owns one instance. */
import * as api from "@/lib/api/conversations";
import { DEMO_MODE, questionCharacters } from "@/lib/demo";
import { sessionOwner, sessionRevision, SESSION_REQUESTS_INVALIDATED_EVENT } from "@/lib/api/session-events";
import type { ConversationMetadata, StoredTurn, TurnStatus, SubmitTurnRequest } from "@/lib/api/conversations";
export type ConversationTransport = Pick<typeof api, "listConversations" | "getConversation" | "createConversation" | "renameConversation" | "deleteConversation" | "submitTurn" | "getTurnStatus" | "interruptExpiredTurn">;
export type ControllerError = {
  category: string;
  message: string;
  conversationId?: string;
};
export type LogicalSubmission = Readonly<{
  conversationId: string;
  payload: Readonly<SubmitTurnRequest>;
  turn: TurnStatus | null;
  phase: "submitting" | "unknown" | "running" | "completed" | "failed" | "interrupted";
}>;
export type ServerConversationState = Readonly<{
  ownerId: string | null;
  sessionRevision: number;
  conversations: readonly ConversationMetadata[];
  nextListCursor: string | null;
  listLoading: boolean;
  selectedId: string | null;
  conversation: ConversationMetadata | null;
  turns: readonly StoredTurn[];
  executionExpired: Readonly<Record<string, boolean>>;
  nextTurnCursor: number | null;
  detailLoading: boolean;
  submission: LogicalSubmission | null;
  polling: boolean;
  metadataLoading: boolean;
  creation: Readonly<{
    requestId: string;
    title?: string;
    uncertain: boolean;
  }> | null;
  error: ControllerError | null;
}>;
// Published snapshots cannot be mutated into a second UI database by consumers.
function immutable<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value))
      immutable(child);
    Object.freeze(value);
  }
  return value;
}
export const EMPTY_SERVER_CONVERSATIONS: ServerConversationState = immutable({
  ownerId: null, sessionRevision: -1, conversations: [], nextListCursor: null, listLoading: false,
  selectedId: null, conversation: null, turns: [], executionExpired: {}, nextTurnCursor: null, detailLoading: false,
  submission: null, polling: false, metadataLoading: false, creation: null, error: null,
});
type Scope = {
  owner: string;
  revision: number;
  epoch: number;
};
type Work = {
  scope: Scope;
  abort: AbortController;
  kind: string;
  cid?: string;
};
// PostgreSQL sidebar order includes microseconds; Date.parse alone loses them.
function activity(value: string): bigint {
  const fraction = /\.(\d+)/.exec(value)?.[1] ?? "";
  return BigInt(Date.parse(value)) * BigInt(1000) + BigInt(fraction.padEnd(6, "0").slice(3, 6));
}
function orderConversations(rows: ConversationMetadata[]): ConversationMetadata[] {
  return rows.sort((a, b) => {
    const x = activity(a.last_activity_at), y = activity(b.last_activity_at);
    return x === y ? (a.id.toLowerCase() === b.id.toLowerCase() ? 0 : a.id.toLowerCase() > b.id.toLowerCase() ? -1 : 1) : x > y ? -1 : 1;
  });
}
function metadata(old: ConversationMetadata | undefined, next: ConversationMetadata): ConversationMetadata {
  if (!old)
    return next;
  return { ...next, ...(old.metadata_version > next.metadata_version ? {
      title: old.title, title_is_manual: old.title_is_manual, metadata_version: old.metadata_version,
    } : {}), content_version: Math.max(old.content_version, next.content_version),
    updated_at: activity(old.updated_at) > activity(next.updated_at) ? old.updated_at : next.updated_at,
    last_activity_at: activity(old.last_activity_at) > activity(next.last_activity_at) ? old.last_activity_at : next.last_activity_at };
}
function mergeTurns(previous: readonly StoredTurn[], incoming: readonly StoredTurn[]): StoredTurn[] {
  const rows = new Map(previous.map(row => [row.id, row]));
  for (const row of incoming) {
    const old = rows.get(row.id);
    // Terminal state is immutable. A stale RUNNING page cannot undo publication.
    if (old && old.status !== "RUNNING") {
      if (row.status !== "RUNNING" && row.status !== old.status)
        throw new Error("Inconsistent durable turn");
      continue;
    }
    rows.set(row.id, row);
  }
  const ordered = [...rows.values()].sort((a, b) => a.sequence - b.sequence);
  if (ordered.some((row, i) => i > 0 && row.sequence === ordered[i - 1].sequence))
    throw new Error("Inconsistent durable order");
  return ordered;
}
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Cancelled", "AbortError"));
      return;
    }
    const cancel = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, ms);
    signal.addEventListener("abort", cancel, { once: true });
  });
}
// Observe cancellation-resistant transports too, without treating HTTP abort as
// server rollback. Both settlement branches are observed; late packets do no work.
function observe<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const cancel = () => reject(new DOMException("Polling paused", "AbortError"));
    if (signal.aborted)
      cancel();
    else
      signal.addEventListener("abort", cancel, { once: true });
    operation.then(value => { signal.removeEventListener("abort", cancel); resolve(value); }, error => { signal.removeEventListener("abort", cancel); reject(error); });
  });
}
export class ServerConversationController {
  private state: ServerConversationState = EMPTY_SERVER_CONVERSATIONS;
  private listeners = new Set<() => void>();
  private work = new Set<Work>();
  private requests = new Map<string, LogicalSubmission>();
  private deleted = new Set<string>();
  private epoch = 0;
  private listGeneration = 0;
  private selectionGeneration = 0;
  private detailGeneration = 0;
  private pollGeneration = 0;
  private mutationGeneration = new Map<string, number>();
  private metadataGeneration = new Map<string, number>();
  private active = false;
  private readonly invalidate = () => this.reset();
  constructor(private readonly transport: ConversationTransport = api) { }
  getSnapshot = (): ServerConversationState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  connect(): void {
    if (this.active)
      return;
    this.active = true;
    if (typeof window !== "undefined")
      window.addEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, this.invalidate);
  }
  dispose(): void {
    this.active = false;
    if (typeof window !== "undefined")
      window.removeEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, this.invalidate);
    this.reset();
  }
  reset(): void {
    this.epoch += 1;
    for (const entry of this.work)
      entry.abort.abort();
    this.work.clear();
    this.requests.clear();
    this.deleted.clear();
    this.mutationGeneration.clear();
    this.metadataGeneration.clear();
    this.listGeneration += 1;
    this.selectionGeneration += 1;
    this.detailGeneration += 1;
    this.pollGeneration += 1;
    this.state = immutable({ ...EMPTY_SERVER_CONVERSATIONS, sessionRevision: sessionRevision() });
    this.emit();
  }
  private emit(): void { for (const listener of this.listeners)
    listener(); }
  private update(patch: Partial<ServerConversationState>): void { this.state = immutable({ ...this.state, ...patch }); this.emit(); }
  private scope(): Scope | null {
    if (!this.active || DEMO_MODE || !this.state.ownerId || sessionOwner() !== this.state.ownerId || sessionRevision() !== this.state.sessionRevision)
      return null;
    return { owner: this.state.ownerId, revision: this.state.sessionRevision, epoch: this.epoch };
  }
  private live(scope: Scope): boolean {
    return this.active && scope.epoch === this.epoch && scope.owner === this.state.ownerId
      && scope.owner === sessionOwner() && scope.revision === sessionRevision();
  }
  private begin(scope: Scope, kind: string, cid?: string): Work {
    const entry = { scope, kind, cid, abort: new AbortController() };
    this.work.add(entry);
    return entry;
  }
  private finish(entry: Work): void { this.work.delete(entry); }
  private valid(entry: Work): boolean { return this.live(entry.scope) && !entry.abort.signal.aborted; }
  private stop(kind: string, cid?: string): void {
    for (const entry of this.work)
      if (entry.kind === kind && (cid === undefined || entry.cid === cid))
        entry.abort.abort();
  }
  private view(entry: Work, selection: number): boolean {
    return this.valid(entry) && this.state.selectedId === entry.cid && this.selectionGeneration === selection && !this.deleted.has(entry.cid!);
  }
  private error(error: unknown, cid?: string, removeOn404 = true): void {
    if (error instanceof api.ConversationApiError) {
      if (removeOn404 && error.status === 404 && cid) {
        this.remove(cid);
        return;
      }
      this.update({ error: { category: error.category, message: error.detail, conversationId: cid } });
    }
    else
      this.update({ error: { category: "unavailable", message: "Conversation state could not be refreshed.", conversationId: cid } });
    // Never call session invalidation here: the adapter/provider own authentication.
  }
  private put(row: ConversationMetadata): void {
    if (this.deleted.has(row.id))
      return;
    const old = this.state.conversations.find(value => value.id === row.id)
      ?? (this.state.conversation?.id === row.id ? this.state.conversation : undefined);
    this.advanceMetadataGeneration(row.id);
    const canonical = metadata(old, row);
    this.update({ conversations: orderConversations([...this.state.conversations.filter(value => value.id !== row.id), canonical]),
      ...(this.state.selectedId === row.id ? { conversation: canonical } : {}) });
  }
  // New metadata reads and accepted canonical snapshots invalidate older metadata outcomes.
  private advanceMetadataGeneration(cid: string): number {
    const generation = (this.metadataGeneration.get(cid) ?? 0) + 1;
    this.metadataGeneration.set(cid, generation);
    return generation;
  }
  private remove(cid: string): void {
    this.deleted.add(cid);
    this.requests.delete(cid);
    this.stop("detail", cid);
    this.stop("poll", cid);
    this.stop("status", cid);
    const selected = this.state.selectedId === cid;
    if (selected) {
      this.selectionGeneration += 1;
      this.detailGeneration += 1;
    }
    this.update({ conversations: this.state.conversations.filter(row => row.id !== cid),
      ...(selected ? { selectedId: null, conversation: null, turns: [], executionExpired: {}, nextTurnCursor: null,
        submission: null, polling: false, metadataLoading: false, detailLoading: false } : {}) });
  }
  async initialize(): Promise<void> {
    this.reset();
    const owner = sessionOwner();
    if (!this.active || DEMO_MODE || !owner)
      return;
    this.update({ ownerId: owner, sessionRevision: sessionRevision() });
    await this.refreshList();
  }
  async refreshList(): Promise<void> { await this.list(false); }
  async loadMoreConversations(): Promise<void> { if (this.state.nextListCursor !== null)
    await this.list(true); }
  private async list(append: boolean): Promise<void> {
    const scope = this.scope();
    if (!scope)
      return;
    this.stop("list");
    const generation = ++this.listGeneration;
    const cursor = append ? this.state.nextListCursor ?? undefined : undefined;
    const entry = this.begin(scope, "list");
    this.update({ listLoading: true, error: null });
    try {
      const result = await this.transport.listConversations({ limit: 30, cursor }, entry.abort.signal);
      if (!this.valid(entry) || generation !== this.listGeneration)
        return;
      const known = new Map(this.state.conversations.map(row => [row.id, row]));
      const rows = new Map((append ? this.state.conversations : []).map(row => [row.id, row]));
      for (const row of result.conversations)
        if (!this.deleted.has(row.id)) {
          this.advanceMetadataGeneration(row.id);
          rows.set(row.id, metadata(known.get(row.id), row));
        }
      const selected = this.state.selectedId ? rows.get(this.state.selectedId) : undefined;
      this.update({ conversations: orderConversations([...rows.values()]), nextListCursor: result.next_cursor,
        ...(selected && this.state.conversation ? { conversation: metadata(this.state.conversation, selected) } : {}) });
    }
    catch (error) {
      if (this.valid(entry) && generation === this.listGeneration)
        this.error(error);
    }
    finally {
      this.finish(entry);
      if (this.valid(entry) && generation === this.listGeneration)
        this.update({ listLoading: false });
    }
  }
  async select(cid: string | null): Promise<void> {
    cid = cid?.toLowerCase() ?? null;
    const scope = this.scope();
    if (!scope)
      return;
    this.stop("detail");
    this.stop("poll");
    this.stop("status");
    const selection = ++this.selectionGeneration;
    this.detailGeneration += 1;
    this.update({ selectedId: cid, conversation: null, turns: [], executionExpired: {}, nextTurnCursor: null,
      submission: cid ? this.requests.get(cid) ?? null : null, polling: false, metadataLoading: false, detailLoading: false, error: null });
    if (cid !== null && !this.deleted.has(cid))
      await this.detail(scope, cid, selection, false);
  }
  async reloadSelected(): Promise<void> {
    const scope = this.scope(), cid = this.state.selectedId;
    if (scope && cid && !this.deleted.has(cid)) {
      this.update({ error: null });
      await this.detail(scope, cid, this.selectionGeneration, false);
    }
  }
  async loadOlderTurns(): Promise<void> {
    const scope = this.scope(), cid = this.state.selectedId;
    if (scope && cid && this.state.nextTurnCursor !== null)
      await this.detail(scope, cid, this.selectionGeneration, true);
  }
  private async detail(scope: Scope, cid: string, selection: number, append: boolean): Promise<void> {
    this.stop("detail", cid);
    const generation = ++this.detailGeneration;
    const before = append ? this.state.nextTurnCursor ?? undefined : undefined;
    const entry = this.begin(scope, "detail", cid);
    this.update({ detailLoading: true });
    try {
      const result = await this.transport.getConversation(cid, { limit: 50, before_sequence: before }, entry.abort.signal);
      if (!this.view(entry, selection) || generation !== this.detailGeneration)
        return;
      this.put(result.conversation);
      const receipt = this.requests.get(cid)?.turn;
      const turns = mergeTurns(append ? this.state.turns : this.state.turns.filter(row => row.id === receipt?.id), result.turns);
      this.update({ turns: receipt ? mergeTurns(turns, [receipt]) : turns, nextTurnCursor: result.next_before_sequence });
    }
    catch (error) {
      if (this.view(entry, selection) && generation === this.detailGeneration)
        this.error(error, cid);
    }
    finally {
      this.finish(entry);
      if (this.view(entry, selection) && generation === this.detailGeneration)
        this.update({ detailLoading: false });
    }
  }
  async create(title?: string): Promise<ConversationMetadata | null> {
    if (!this.scope())
      return null;
    if (this.state.creation) {
      this.update({ error: { category: "pending_creation", message: "Reconcile the previous creation first." } });
      return null;
    }
    this.update({ creation: Object.freeze({ requestId: crypto.randomUUID(), title, uncertain: false }) });
    return await this.retryCreate();
  }
  async retryCreate(): Promise<ConversationMetadata | null> {
    const scope = this.scope(), pending = this.state.creation;
    if (!scope || !pending)
      return null;
    const selection = this.selectionGeneration;
    const entry = this.begin(scope, "create");
    try {
      const result = await this.transport.createConversation({ create_request_id: pending.requestId, ...(pending.title === undefined ? {} : { title: pending.title }) }, entry.abort.signal);
      if (!this.valid(entry) || this.state.creation?.requestId !== pending.requestId)
        return null;
      this.listGeneration += 1;
      this.stop("list");
      this.put(result.conversation);
      this.update({ creation: null, listLoading: false, error: null });
      if (selection === this.selectionGeneration)
        await this.select(result.conversation.id);
      return this.live(scope) ? result.conversation : null;
    }
    catch (error) {
      if (this.valid(entry) && this.state.creation?.requestId === pending.requestId) {
        this.update({ creation: { ...pending, uncertain: true } });
        this.error(error);
      }
      return null;
    }
    finally {
      this.finish(entry);
    }
  }
  async rename(cid: string, title: string): Promise<boolean> {
    cid = cid.toLowerCase();
    const scope = this.scope(), row = this.state.conversations.find(value => value.id === cid) ?? (this.state.conversation?.id === cid ? this.state.conversation : null);
    if (!scope || !row || this.deleted.has(cid))
      return false;
    const version = (this.mutationGeneration.get(cid) ?? 0) + 1;
    this.mutationGeneration.set(cid, version);
    const entry = this.begin(scope, "rename", cid);
    try {
      const result = await this.transport.renameConversation(cid, { title, expected_metadata_version: row.metadata_version }, entry.abort.signal);
      if (!this.valid(entry) || this.deleted.has(cid) || this.mutationGeneration.get(cid) !== version)
        return false;
      this.put(result);
      this.update({ error: null });
      return true;
    }
    catch (error) {
      if (this.valid(entry) && !this.deleted.has(cid) && this.mutationGeneration.get(cid) === version) {
        this.error(error, cid);
        if (error instanceof api.ConversationApiError && error.status === 409)
          await this.refreshMetadata(scope, cid);
      }
      return false;
    }
    finally {
      this.finish(entry);
    }
  }
  async delete(cid: string): Promise<boolean> {
    cid = cid.toLowerCase();
    const scope = this.scope(), row = this.state.conversations.find(value => value.id === cid) ?? (this.state.conversation?.id === cid ? this.state.conversation : null);
    if (!scope || !row || this.deleted.has(cid))
      return false;
    const entry = this.begin(scope, "delete", cid);
    try {
      await this.transport.deleteConversation(cid, row.metadata_version, entry.abort.signal);
      if (!this.valid(entry))
        return false;
      this.listGeneration += 1;
      this.stop("list");
      this.stop("submit", cid);
      this.remove(cid);
      this.update({ listLoading: false, error: null });
      return true;
    }
    catch (error) {
      if (this.valid(entry)) {
        this.error(error, cid);
        if (error instanceof api.ConversationApiError && error.status === 409)
          await this.refreshMetadata(scope, cid);
      }
      return false;
    }
    finally {
      this.finish(entry);
    }
  }
  private async refreshMetadata(scope: Scope, cid: string, signal?: AbortSignal): Promise<void> {
    if (!this.live(scope) || this.deleted.has(cid) || signal?.aborted)
      return;
    const generation = this.advanceMetadataGeneration(cid);
    const entry = this.begin(scope, "metadata", cid);
    // Bound our wait even if the transport ignores cancellation; late outcomes stay observed.
    const cancel = () => entry.abort.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const current = () => this.valid(entry) && !this.deleted.has(cid) && this.metadataGeneration.get(cid) === generation;
    if (this.state.selectedId === cid)
      this.update({ metadataLoading: true });
    try {
      const detail = await observe(this.transport.getConversation(cid, { limit: 1 }, entry.abort.signal), entry.abort.signal);
      if (current())
        this.put(detail.conversation);
    }
    catch (error) {
      if (current()) {
        if (error instanceof api.ConversationApiError && error.status === 404)
          this.remove(cid);
        else if (this.state.selectedId === cid)
          this.error(error, cid);
      }
    }
    finally {
      signal?.removeEventListener("abort", cancel);
      this.finish(entry);
      // Aborted work still owns loading cleanup, but never across an account/epoch change.
      if (this.live(scope) && this.state.selectedId === cid)
        this.update({ metadataLoading: [...this.work].some(work => work.kind === "metadata" && work.cid === cid && !work.abort.signal.aborted) });
    }
  }
  async submitQuestion(question: string): Promise<void> {
    const scope = this.scope(), row = this.state.conversation;
    if (!scope || !row || this.state.detailLoading || this.state.metadataLoading || row.id !== this.state.selectedId || this.deleted.has(row.id))
      return;
    if ([...this.work].some(entry => entry.kind === "submit" && entry.cid === row.id && !entry.abort.signal.aborted))
      return;
    const prior = this.requests.get(row.id);
    if (this.state.turns.some(turn => turn.status === "RUNNING") || (prior && ["submitting", "running", "unknown"].includes(prior.phase))) {
      this.update({ error: { category: "pending_submission", message: "Reconcile the existing submission before starting another." } });
      return;
    }
    if (!question.trim() || questionCharacters(question) > 4000) {
      this.update({ error: { category: "invalid_request", message: "Enter a question of at most 4,000 characters." } });
      return;
    }
    const request: LogicalSubmission = Object.freeze({ conversationId: row.id,
      payload: Object.freeze({ client_request_id: crypto.randomUUID(), question, expected_content_version: row.content_version }),
      turn: null, phase: "submitting" });
    this.requests.set(row.id, request);
    this.update({ submission: request, error: null });
    await this.sendSubmission(scope, request);
  }
  async reconcileSubmission(): Promise<void> {
    const scope = this.scope(), cid = this.state.selectedId, request = cid ? this.requests.get(cid) : undefined;
    if (!scope || !request || request.phase === "submitting")
      return;
    if (request.turn)
      await this.refreshTurn(request.turn.id);
    else
      await this.sendSubmission(scope, request); // Exact original UUID/body, including content version.
  }
  cancelSubmission(): void {
    const cid = this.state.selectedId, request = cid ? this.requests.get(cid) : undefined;
    if (!cid || !request || !this.scope())
      return;
    const pending = Object.freeze({ ...request, phase: "unknown" as const });
    this.requests.set(cid, pending);
    this.update({ submission: pending });
    this.stop("submit", cid);
  }
  private currentRequest(scope: Scope, request: LogicalSubmission): boolean {
    return this.live(scope) && !this.deleted.has(request.conversationId)
      && this.requests.get(request.conversationId)?.payload.client_request_id === request.payload.client_request_id;
  }
  private accept(scope: Scope, cid: string, turn: TurnStatus, request?: LogicalSubmission): void {
    if (!this.live(scope) || this.deleted.has(cid))
      return;
    if (request && (!this.currentRequest(scope, request) || turn.client_request_id !== request.payload.client_request_id))
      return;
    const logical = this.requests.get(cid);
    let next = logical;
    if (logical && logical.payload.client_request_id === turn.client_request_id) {
      if (logical.turn && logical.turn.status !== "RUNNING" && turn.status === "RUNNING")
        turn = logical.turn;
      next = Object.freeze({ ...logical, turn, phase: turn.status.toLowerCase() as LogicalSubmission["phase"] });
      this.requests.set(cid, next);
    }
    if (this.state.selectedId === cid) {
      const turns = mergeTurns(this.state.turns, [turn]);
      const current = turns.find(row => row.id === turn.id);
      this.update({ turns, executionExpired: { ...this.state.executionExpired,
          [turn.id]: current?.status === "RUNNING" && turn.execution_expired }, submission: next ?? null });
    }
  }
  private async sendSubmission(scope: Scope, request: LogicalSubmission): Promise<void> {
    if (!this.currentRequest(scope, request))
      return;
    // No second local send while this logical request is already in flight.
    if ([...this.work].some(entry => entry.kind === "submit" && entry.cid === request.conversationId && !entry.abort.signal.aborted))
      return;
    const entry = this.begin(scope, "submit", request.conversationId);
    try {
      const result = await this.transport.submitTurn(request.conversationId, request.payload, entry.abort.signal);
      if (!this.valid(entry) || !this.currentRequest(scope, request))
        return;
      this.accept(scope, request.conversationId, result.turn, request);
      await this.refreshMetadata(scope, request.conversationId);
    }
    catch (error) {
      if (!this.valid(entry) || !this.currentRequest(scope, request))
        return;
      if (error instanceof api.ConversationApiError && error.receipt)
        this.accept(scope, request.conversationId, error.receipt.turn, request);
      else {
        const unknown = Object.freeze({ ...request, phase: "unknown" as const });
        this.requests.set(request.conversationId, unknown);
        if (this.state.selectedId === request.conversationId)
          this.update({ submission: unknown });
      }
      if (this.state.selectedId === request.conversationId)
        this.error(error, request.conversationId);
      if (error instanceof api.ConversationApiError && error.receipt)
        await this.refreshMetadata(scope, request.conversationId);
    }
    finally {
      this.finish(entry);
    }
  }
  async refreshTurn(turnId: string): Promise<void> {
    turnId = turnId.toLowerCase();
    const scope = this.scope(), cid = this.state.selectedId, selection = this.selectionGeneration;
    if (!scope || !cid || this.deleted.has(cid))
      return;
    const entry = this.begin(scope, "status", cid);
    try {
      const result = await this.transport.getTurnStatus(cid, turnId, entry.abort.signal);
      if (!this.view(entry, selection) || result.id !== turnId)
        return;
      this.accept(scope, cid, result);
      if (result.status !== "RUNNING")
        await this.refreshMetadata(scope, cid);
    }
    catch (error) {
      if (this.view(entry, selection))
        this.error(error, cid, false);
    }
    finally {
      this.finish(entry);
    }
  }
  async interruptExpiredTurn(turnId: string): Promise<void> {
    turnId = turnId.toLowerCase();
    const scope = this.scope(), cid = this.state.selectedId, selection = this.selectionGeneration;
    // Calling this method is explicit user intent, not an automatic expiry policy.
    if (!scope || !cid)
      return;
    const entry = this.begin(scope, "interrupt", cid);
    try {
      const result = await this.transport.interruptExpiredTurn(cid, turnId, entry.abort.signal);
      if (!this.view(entry, selection) || result.id !== turnId)
        return;
      this.accept(scope, cid, result);
      await this.refreshMetadata(scope, cid);
    }
    catch (error) {
      if (this.view(entry, selection))
        this.error(error, cid, false);
    }
    finally {
      this.finish(entry);
    }
  }
  async pollTurn(turnId: string, options: {
    maxAttempts?: number;
    intervalMs?: number;
  } = {}): Promise<void> {
    turnId = turnId.toLowerCase();
    const maxAttempts = options.maxAttempts ?? 30, intervalMs = options.intervalMs ?? 2000;
    if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 60 || !Number.isInteger(intervalMs) || intervalMs < 100 || maxAttempts * intervalMs > 180000)
      return;
    const scope = this.scope(), cid = this.state.selectedId, selection = this.selectionGeneration;
    if (!scope || !cid)
      return;
    this.stop("poll");
    const generation = ++this.pollGeneration;
    const entry = this.begin(scope, "poll", cid);
    this.update({ polling: true });
    const deadline = setTimeout(() => entry.abort.abort(), Math.max(5000, maxAttempts * intervalMs));
    try {
      for (let n = 0; n < maxAttempts && this.view(entry, selection); n += 1) {
        const result = await observe(this.transport.getTurnStatus(cid, turnId, entry.abort.signal), entry.abort.signal);
        if (!this.view(entry, selection) || result.id !== turnId)
          return;
        this.accept(scope, cid, result);
        if (result.status !== "RUNNING" || result.execution_expired) {
          if (result.status !== "RUNNING")
            await this.refreshMetadata(scope, cid, entry.abort.signal);
          return; // Expired work requires an explicit interruption, never replay.
        }
        if (n + 1 < maxAttempts)
          await wait(intervalMs, entry.abort.signal);
      }
    }
    catch (error) {
      if (this.view(entry, selection))
        this.error(error, cid, false);
    }
    finally {
      clearTimeout(deadline);
      this.finish(entry);
      if (this.live(scope) && this.state.selectedId === cid && this.selectionGeneration === selection && this.pollGeneration === generation)
        this.update({ polling: false });
    }
  }
  stopPolling(): void { this.pollGeneration += 1; this.stop("poll"); if (this.scope())
    this.update({ polling: false }); }
}
