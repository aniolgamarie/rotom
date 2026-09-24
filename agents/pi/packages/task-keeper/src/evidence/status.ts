import { finiteInteger, systemClock, type Clock } from "../contracts/primitives.ts";

export function recoveryStatusText(record: { status: string; reason: string; notBefore: number; attempts: number; intentId: string | null; deadlineAt?: number | null }, now: number) {
  let text = `${record.status} · ${record.reason}`;
  if (record.status === "WAITING_QUOTA") {
    text += !Number.isFinite(record.notBefore) ? " · wait unknown" : record.notBefore > now
      ? ` · wait >=${Math.ceil((record.notBefore - now) / 1000)}s` : " · awaiting admission";
    if (record.deadlineAt != null) text += ` · deadline ${Math.max(0, Math.ceil((record.deadlineAt - now) / 1000))}s`;
  }
  if (["BLOCKED", "PAUSED"].includes(record.status) && record.intentId) text += " · execution unreconciled";
  return `${text} · attempts ${record.attempts}`;
}

export interface JobStatusView { id: string; status: string; reason: string; snapshot: string | null; routeNotBefore?: number; stageDeadline?: number | null; scheduleNotBefore?: number | null }
export function jobStatusText(job: JobStatusView, now: number) {
  let text = `${job.id.slice(-8)}:${job.status}`;
  if (["COMPLETED", "PARTIAL"].includes(job.status) && job.snapshot) text += `@${job.snapshot.slice(-8)}`;
  if(job.status === "QUEUED" && job.scheduleNotBefore!=null)text+=` · start >=${Math.max(0,Math.ceil((job.scheduleNotBefore-now)/1000))}s`;
  if(job.status === "PAUSED" && job.reason.includes("scheduled"))text+=` · ${job.reason}`;
  if (job.status === "WAITING_QUOTA") {
    text += job.routeNotBefore === undefined ? " · route wait unknown" : ` · route >=${Math.max(0, Math.ceil((job.routeNotBefore - now) / 1000))}s`;
    if (job.stageDeadline != null) text += ` · stage ${Math.max(0, Math.ceil((job.stageDeadline - now) / 1000))}s`;
  } else if (job.status === "BLOCKED") text += ` · ${job.reason.slice(0, 80)}`;
  return text;
}

interface Channel {
  identity: string; render: (now: number) => string; refresh: boolean; pending: boolean; retry: boolean;
  lastText: string | null; lastAttempt: number;
}
/** Presentation only: coalesce updates, refresh countdowns, and retire callbacks with their session. */
export class StatusPublisher {
  private channels = new Map<string, Channel>();
  private cancelTimer: (() => void) | null = null;
  private timerAt = Infinity;
  private disposed = false;
  private emit: (key: string, value: string | undefined) => void;
  private clock: Clock;
  private interval: number;
  constructor(emit: (key: string, value: string | undefined) => void, clock: Clock = systemClock, intervalMs = 1000) {
    finiteInteger(intervalMs, 1, 60000); this.emit = emit; this.clock = clock; this.interval = intervalMs;
  }
  publish(key: string, identity: string, render: (now: number) => string, refresh = false): void {
    if (this.disposed) return;
    const previous = this.channels.get(key), critical = !previous || previous.identity !== identity;
    const channel: Channel = previous ?? { identity, render, refresh, pending: true, retry: false, lastText: null, lastAttempt: -Infinity };
    Object.assign(channel, { identity, render, refresh, pending: true }); this.channels.set(key, channel);
    if (critical || this.clock.monotonic() >= channel.lastAttempt + this.interval) this.flush(key, channel);
    this.schedule();
  }
  private flush(key: string, channel: Channel): void {
    channel.pending = false;
    let text: string;
    try { text = channel.render(this.clock.now()); } catch { text = "UNKNOWN · status unavailable"; }
    if (text !== channel.lastText || channel.retry) {
      try { this.emit(key, text); channel.lastText = text; channel.retry = false; }
      catch { channel.retry = true; }
    }
    channel.lastAttempt = this.clock.monotonic();
  }
  private schedule(): void {
    if (this.disposed) return;
    const at = Math.min(...[...this.channels.values()].filter(channel => channel.refresh || channel.pending || channel.retry)
      .map(channel => channel.lastAttempt + this.interval));
    if (at === Infinity) { this.cancelTimer?.(); this.cancelTimer = null; this.timerAt = Infinity; return; }
    if (this.cancelTimer && this.timerAt <= at) return;
    this.cancelTimer?.(); this.timerAt = at;
    this.cancelTimer = this.clock.schedule(Math.max(1, Math.ceil(at - this.clock.monotonic())), () => {
      this.cancelTimer = null; this.timerAt = Infinity; if (this.disposed) return;
      for (const [key, channel] of this.channels) if ((channel.refresh || channel.pending || channel.retry)
        && this.clock.monotonic() >= channel.lastAttempt + this.interval) this.flush(key, channel);
      this.schedule();
    });
  }
  dispose(): void {
    if (this.disposed) return; this.disposed = true; this.cancelTimer?.(); this.cancelTimer = null;
    for (const key of this.channels.keys()) try { this.emit(key, undefined); } catch { /* Optional UI cannot control execution cleanup. */ }
    this.channels.clear();
  }
}
