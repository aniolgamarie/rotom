import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import type { TestContext } from "node:test";
import type { Server } from "node:http";
import { randomInt } from "node:crypto";
import type { Clock } from "../src/contracts/primitives.ts";

export function isolatedDirectory(t: TestContext): string {
  if (process.env.TASK_KEEPER_ISOLATED !== "1" || !process.env.TASK_KEEPER_TEST_WORK_ROOT) throw new Error("Use the isolated test launcher");
  // The namespace supervisor owns deletion, after all test cleanup hooks and child processes end.
  return mkdtempSync(join(process.env.TASK_KEEPER_TEST_WORK_ROOT, "pi-task-keeper-test-"));
}

export async function listenLoopback(server: Server): Promise<number> {
  // This host permits ephemeral ports as low as 3500, including Fetch's blocked service ports.
  for (let attempt = 0; attempt < 32; attempt++) {
    const port = randomInt(32768, 60999);
    const listening = await new Promise<boolean>((resolve, reject) => {
      const ready = () => { server.off("error", failed); resolve(true); };
      const failed = (error: NodeJS.ErrnoException) => { server.off("listening", ready); if (error.code === "EADDRINUSE") resolve(false); else reject(error); };
      server.once("error", failed); server.once("listening", ready); server.listen(port, "127.0.0.1");
    });
    if (listening) return port;
  }
  throw new Error("Could not allocate a Fetch-safe loopback fixture port");
}

export class FakeClock implements Clock {
  wall = 1_000_000;
  mono = 0;
  private serial = 0;
  private timers = new Map<number, { at: number; callback: () => void }>();
  now(): number { return this.wall; }
  monotonic(): number { return this.mono; }
  schedule(delayMs: number, callback: () => void): () => void {
    const id = ++this.serial;
    this.timers.set(id, { at: this.mono + delayMs, callback });
    return () => { this.timers.delete(id); };
  }
  advance(ms: number): void {
    this.wall += ms;
    this.mono += ms;
    // Snapshot prevents catch-up storms and makes newly scheduled work explicit.
    const due = [...this.timers.entries()].filter(([, timer]) => timer.at <= this.mono);
    for (const [id, timer] of due) if (this.timers.delete(id)) timer.callback();
  }
  get pending(): number { return this.timers.size; }
}

export function barrier<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export class FakeAdapter {
  actions: Array<{ kind: string; id: string }> = [];
  blocked = false;
  next = barrier<string>();
  async start(id: string): Promise<string> {
    this.actions.push({ kind: "start", id });
    return this.next.promise;
  }
  cancel(id: string): void { this.actions.push({ kind: "cancel", id }); }
}

export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}
