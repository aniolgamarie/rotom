// 自有公开事件流替身：terminal push立即解决result，测试持久化之前不得发布。
export class PublicEventStream {
  constructor() {
    this.queue = []; this.waiters = []; this.ended = false;
    this.completed = new Promise(resolve => { this.resolve = resolve; });
  }
  push(event) {
    if (this.ended) return;
    if (event.type === "done" || event.type === "error") {
      this.resolve(event.type === "done" ? event.message : event.error);
      this.ended = true;
    }
    this.queue.push(event);
    for (const wake of this.waiters.splice(0)) wake();
  }
  end(message) {
    if (!this.ended) this.resolve(message);
    this.ended = true; for (const wake of this.waiters.splice(0)) wake();
  }
  result() { return this.completed; }
  async *[Symbol.asyncIterator]() {
    while (this.queue.length || !this.ended) {
      if (this.queue.length) yield this.queue.shift();
      else await new Promise(resolve => this.waiters.push(resolve));
    }
  }
}
export const factory = { createAssistantMessageEventStream() { return new PublicEventStream(); } };
export function rawStream(events, message, options = {}) {
  return { async *[Symbol.asyncIterator]() {
    if (options.gate) await options.gate.promise;
    for (const event of events) yield event;
    if (options.throwAfter) throw options.throwAfter;
  }, async result() {
    if (options.resultGate) await options.resultGate.promise;
    if (options.resultReject) throw options.resultReject;
    return message;
  } };
}
export const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
