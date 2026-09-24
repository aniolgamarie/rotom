// 一次性调度只有 Task Keeper 驱动；本模块不创建后台计时器或唤醒宿主。
import { randomUUID } from "node:crypto";
import { clone, closed, digest, reject, text } from "./managed-types.ts";

export class OneShotScheduler {
  constructor({ store, dispatcher, authorizeUser, now = () => Date.now() }) {
    this.store = store; this.dispatcher = dispatcher; this.authorizeUser = authorizeUser; this.now = now;
    this.startedAt = now(); this.closed = false;
  }
  user() { if (this.authorizeUser() !== true) reject("USER_CONTROL_REQUIRED", 4); }
  async schedule(request) {
    this.user();
    closed(request, ["task_id", "budget_scope_id", "due_at", "deadline", "idempotency_key"]);
    if (["task_id", "budget_scope_id", "idempotency_key"].some(key => !text(request[key]))
        || !Number.isFinite(Date.parse(request.due_at)) || !Number.isFinite(Date.parse(request.deadline))
        || Date.parse(request.deadline) <= Date.parse(request.due_at)) reject();
    let record;
    await this.store.transaction(state => {
      state.schedules ??= {};
      const key = digest(request.idempotency_key);
      const existing = state.schedules[key];
      if (existing) {
        if (existing.request_digest !== digest(request)) reject("SCHEDULE_CONFLICT", 4);
        record = clone(existing);
      } else {
        if (Date.parse(request.due_at) < this.now()) reject();
        record = { ...clone(request), schedule_id: randomUUID(), request_digest: digest(request), state: "scheduled", admitted_at: null, dispatch_id: null };
        state.schedules[key] = record;
      }
    });
    return record;
  }
  async tick() {
    if (this.closed) return [];
    const admitted = [];
    await this.store.transaction(state => {
      for (const record of Object.values(state.schedules ?? {})) {
        if (record.state !== "scheduled") continue;
        if (Date.parse(record.deadline) <= this.now()) record.state = "expired";
        else if (Date.parse(record.due_at) < this.startedAt) record.state = "paused-missed";
        else if (Date.parse(record.due_at) <= this.now()) {
          record.state = "admitted";
          record.admitted_at = new Date(this.now()).toISOString();
          admitted.push(clone(record));
        }
      }
    });
    const results = [];
    for (const record of admitted) {
      if (this.closed) break;
      // admitted 先于 dispatch 持久化；确认丢失后保持 admitted，不能 tick 自动重发。
      try {
        const result = await this.dispatcher.dispatch(clone(record));
        if (!result || !text(result.dispatch_id)) reject("DISPATCH_IDENTITY", 4);
        await this.store.transaction(state => {
          const saved = state.schedules[digest(record.idempotency_key)];
          saved.state = "executed";
          saved.dispatch_id = result.dispatch_id;
        });
        results.push({ schedule_id: record.schedule_id, state: "executed" });
      } catch {
        results.push({ schedule_id: record.schedule_id, state: "admitted", dispatch_status: "start_unknown" });
      }
    }
    return results;
  }
  async update(scheduleId, action, dueAt = null) {
    this.user();
    if (!["cancel", "resume"].includes(action)) reject();
    let result;
    await this.store.transaction(state => {
      const record = Object.values(state.schedules ?? {}).find(item => item.schedule_id === scheduleId);
      if (!record) reject("SCHEDULE_NOT_FOUND", 4);
      if (action === "cancel") {
        if (!["scheduled", "paused-missed", "canceled"].includes(record.state)) reject("SCHEDULE_ALREADY_ADMITTED", 4);
        record.state = "canceled";
      } else {
        if (record.state !== "paused-missed" || !Number.isFinite(Date.parse(dueAt))
            || Date.parse(dueAt) < this.now() || Date.parse(dueAt) >= Date.parse(record.deadline)) reject("SCHEDULE_RESUME_INVALID", 4);
        record.due_at = dueAt;
        record.state = "scheduled";
      }
      result = clone(record);
    });
    return result;
  }
  close() { this.closed = true; }
}
