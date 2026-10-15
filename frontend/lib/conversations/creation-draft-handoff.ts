import { sessionOwner, sessionRevision } from "@/lib/api/session-events";

type Ticket = {
  owner: string;
  revision: number;
  creationId: string;
  conversationId: string;
  text: string;
  submittedRequestId?: string;
};

/** One authorized creation transition, owned by the mounted normal provider.
 * Not history or a draft cache: consumed once, expires after 60s, never persisted.
 */
export class CreationDraftHandoff {
  private pending: Ticket | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private reconciler: (() => void) | null = null;
  registerReconciler(action: () => void): () => void {
    this.reconciler = action;
    return () => { if (this.reconciler === action) this.reconciler = null; };
  }
  reconcile(): boolean {
    if (!this.reconciler) return false;
    this.reconciler();
    return true;
  }
  clear = () => {
    clearTimeout(this.timer);
    this.timer = undefined;
    this.pending = null;
  };
  private current(ticket: Ticket) {
    return ticket.owner === sessionOwner() && ticket.revision === sessionRevision();
  }
  stage(ticket: Ticket): Ticket | null {
    if (!this.current(ticket) || this.pending) return null;
    this.pending = ticket;
    this.timer = setTimeout(this.clear, 60_000);
    return ticket;
  }
  update(ticket: Ticket | null, text: string) {
    if (ticket && this.pending === ticket && this.current(ticket)) {
      ticket.text = text;
      ticket.submittedRequestId = undefined;
    }
  }
  navigate(path: string | null) {
    if (this.pending && path !== null && path !== `/chat/${this.pending.conversationId}`) this.clear();
  }
  take(owner: string | null, revision: number, conversationId: string | null): Ticket | null {
    const ticket = this.pending;
    if (!ticket) return null;
    this.clear();
    return this.current(ticket) && ticket.owner === owner && ticket.revision === revision
      && ticket.conversationId === conversationId ? ticket : null;
  }
}
