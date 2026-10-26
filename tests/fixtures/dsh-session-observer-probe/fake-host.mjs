import { pathToFileURL } from "node:url";
import { installObservationScene } from "./scene.mjs";
import { createEmitter } from "./attempt.mjs";

// 仓库自有 Node 子进程；只模拟公开 props/scene 元数据，不加载官方包或原生存储。
export function startFakeHost({ mode = "scene", actualCwd = "/synthetic/project" } = {}) {
  let started = false;
  let finished = false;
  let control;
  const cleanups = [];
  const listeners = new Set();
  const rows = new Map();
  let active;
  let notify;
  let agentState = "initializing";
  const lifetime = setTimeout(() => finish(), 4000);
  const channel = { version: 1, ready: true, startupFailure: undefined, status: "idle",
    sessionRef: { backendId: "dsh", sessionId: "synthetic-session" }, sessionId: "synthetic-session",
    cwd: actualCwd, agentBindingGeneration: 1,
    subscribe(callback) { notify = callback; return () => { notify = undefined; }; } };
  for (const key of ["rows", "body", "history", "trace"]) {
    Object.defineProperty(channel, key, { get() { throw Error("body access forbidden"); } });
  }
  const scenes = {
    get active() { return active; },
    register(row) { rows.set(row.id, row); return () => { rows.delete(row.id); }; },
    open(id) { active = rows.get(id); for (const fn of [...listeners]) fn(); return !!active; },
    close() { active = undefined; for (const fn of [...listeners]) fn(); },
    subscribe(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
  };
  const ctx = { tuiScenes: scenes, effect(factory) {
    const cleanup = factory(); if (typeof cleanup === "function") cleanups.push(cleanup);
  } };
  function finish() {
    if (finished) return;
    finished = true;
    clearTimeout(lifetime);
    control?.close();
    for (const fn of cleanups.reverse()) fn();
    process.removeListener("message", receive);
    process.removeListener("disconnect", finish);
    if (process.connected) process.disconnect();
  }
  function receive(request) {
    if (request?.control === "finish") { finish(); return; }
    if (started || finished) return;
    started = true;
    if (mode === "exit" || mode === "disconnect") { finish(); return; }
    const send = mode === "stdout-only"
      ? message => { process.stdout.write(JSON.stringify(message) + "\n"); }
      : message => { if (process.connected && !finished) process.send(message, () => {}); };
    const emit = createEmitter(request, send);
    control = installObservationScene(ctx, {
      onObservation(value) {
        emit(value);
        if (mode === "late-init-failure" && value.kind === "foreground-observed") {
          // 假反例：已注册的 agent 仍在初始化，公开 idle/ready 不是初始化成功回执。
          setImmediate(() => {
            if (finished || agentState !== "initializing") return;
            agentState = "failed";
            channel.version++; channel.ready = false; channel.status = "disposed";
            notify?.();
          });
        }
      },
      onUnavailable(value) { emit(value); },
    });
    const React = {
      useEffect(factory) { const cleanup = factory(); if (typeof cleanup === "function") cleanups.push(cleanup); },
      createElement(type, props, ...children) { return { type, props, children }; },
    };
    active.component({ React, ui: { Text: "synthetic-host-text" }, channel,
      close() { throw Error("fixture must close through its owner"); } });
  }
  process.on("message", receive);
  process.once("disconnect", finish);
  return finish;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startFakeHost({ mode: process.argv[2] ?? "scene" });
}
