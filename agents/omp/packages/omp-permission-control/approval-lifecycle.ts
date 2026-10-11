export interface LifecycleLimits {
  contextTimeoutMs: number;
  queueTimeoutMs: number;
  pollIntervalMs: number;
  reviewConcurrency: number;
}

export const DEFAULT_LIFECYCLE_LIMITS: LifecycleLimits = {
  contextTimeoutMs: 5000,
  queueTimeoutMs: 120000,
  pollIntervalMs: 50,
  reviewConcurrency: 2,
};

export class LifecycleFailure extends Error {
  constructor(readonly reasonCode: "CANCELLED" | "CONTEXT_TIMEOUT" | "REVIEW_QUEUE_TIMEOUT") {
    super(reasonCode);
  }
}

export function lifecycleLimits(overrides: Partial<LifecycleLimits> = {}): LifecycleLimits {
  const limits = { ...DEFAULT_LIFECYCLE_LIMITS, ...overrides };
  if (Object.keys(overrides).some(key => !(key in DEFAULT_LIFECYCLE_LIMITS)) ||
      Object.values(limits).some(value => !Number.isSafeInteger(value) || value < 1) ||
      limits.reviewConcurrency > 16) throw new Error("invalid lifecycle limits");
  return limits;
}

// 底层 opaque Promise 可以迟到，但已取消的等待不会继续占队列或取得执行权。
export function waitFor<T>(operation: () => Promise<T>, signal: AbortSignal,
  timeoutMs?: number, timeoutCode: "CONTEXT_TIMEOUT" | "REVIEW_QUEUE_TIMEOUT" = "CONTEXT_TIMEOUT"): Promise<T> {
  if (signal.aborted) return Promise.reject(new LifecycleFailure("CANCELLED"));
  return new Promise<T>((resolve, reject) => {
    let done = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (value: T | undefined, error?: unknown) => {
      if (done) return;
      done = true;
      if (timer !== undefined) clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      if (error !== undefined) reject(error); else resolve(value as T);
    };
    const abort = () => finish(undefined, new LifecycleFailure("CANCELLED"));
    signal.addEventListener("abort", abort, { once: true });
    if (timeoutMs !== undefined) timer = setTimeout(() => finish(undefined, new LifecycleFailure(timeoutCode)), timeoutMs);
    Promise.resolve().then(() => {
      if (signal.aborted || done) throw new LifecycleFailure("CANCELLED");
      return operation();
    }).then(value => finish(value), error => finish(undefined, error));
  });
}

interface Waiting {
  signal: AbortSignal;
  resolve: (release: () => void) => void;
  reject: (error: LifecycleFailure) => void;
  abort: () => void;
  timer?: ReturnType<typeof setTimeout>;
}

// 模型与人工各自持有有界队列；同一 permit 只能释放一次。
export class ApprovalQueue {
  private active = 0;
  private readonly waiting: Waiting[] = [];
  constructor(private readonly capacity: number) {}

  get status() { return { active: this.active, queued: this.waiting.length }; }

  acquire(signal: AbortSignal, timeoutMs?: number): Promise<() => void> {
    if (signal.aborted) return Promise.reject(new LifecycleFailure("CANCELLED"));
    return new Promise((resolve, reject) => {
      const entry: Waiting = { signal, resolve, reject, abort: () => remove("CANCELLED") };
      const remove = (reason: "CANCELLED" | "REVIEW_QUEUE_TIMEOUT") => {
        const index = this.waiting.indexOf(entry);
        if (index < 0) return;
        this.waiting.splice(index, 1);
        this.cleanup(entry);
        reject(new LifecycleFailure(reason));
      };
      signal.addEventListener("abort", entry.abort, { once: true });
      if (timeoutMs !== undefined) entry.timer = setTimeout(() => remove("REVIEW_QUEUE_TIMEOUT"), timeoutMs);
      this.waiting.push(entry);
      this.drain();
    });
  }

  private cleanup(entry: Waiting) {
    entry.signal.removeEventListener("abort", entry.abort);
    if (entry.timer !== undefined) clearTimeout(entry.timer);
  }

  private drain() {
    while (this.active < this.capacity && this.waiting.length) {
      const entry = this.waiting.shift()!;
      this.cleanup(entry);
      if (entry.signal.aborted) { entry.reject(new LifecycleFailure("CANCELLED")); continue; }
      this.active++;
      let released = false;
      entry.resolve(() => {
        if (released) return;
        released = true;
        this.active--;
        this.drain();
      });
    }
  }
}
