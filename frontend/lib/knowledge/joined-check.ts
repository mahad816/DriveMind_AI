/**
 * Lets a "Check status" click do something real while the same controller is already busy.
 *
 * Controllers used to drop such a click (`if (busy) return`), so the button looked inert,
 * especially because the screens also poll every few seconds. Now:
 *  - a click during a status check JOINS that check and resolves when it really finishes;
 *  - a click during another operation (submit/confirm/close) waits for it, then checks.
 * Internal callers must keep invoking `join` only while not inside their own busy section,
 * so a controller can never wait on itself.
 */
export class JoinedCheck {
  private flag = false;
  private current: Promise<void> | null = null;
  private waiters: (() => void)[] = [];
  get busy() { return this.flag; }
  set busy(value: boolean) {
    this.flag = value;
    if (!value) { const woken = this.waiters; this.waiters = []; woken.forEach(wake => wake()); }
  }
  join(body: () => Promise<void>): Promise<void> {
    if (this.current) return this.current;
    if (this.flag) return new Promise<void>(resolve => this.waiters.push(resolve)).then(() => this.join(body));
    const run = body().finally(() => { if (this.current === run) this.current = null; });
    this.current = run;
    return run;
  }
}
