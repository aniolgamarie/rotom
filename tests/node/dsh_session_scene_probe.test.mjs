import assert from "node:assert/strict";
import test from "node:test";
import { installObservationScene } from "../fixtures/dsh-session-observer-probe/scene.mjs";

const settle = () => new Promise(resolve => setImmediate(resolve));

// 只模拟公开 scene 注册表与注入的 hooks；不加载 React、TUI 或原生宿主。
function scenesHarness(failure) {
  const rows = new Map();
  const listeners = new Set();
  const effects = [];
  const trace = [];
  let active;
  const emit = () => { for (const fn of [...listeners]) fn(); };
  const scenes = {
    get active() { return active; },
    register(row) {
      trace.push("register");
      if (failure === "register") throw Error("synthetic-private-register");
      rows.set(row.id, row);
      return () => {
        trace.push("unregister"); rows.delete(row.id);
        if (active?.id === row.id) { active = undefined; emit(); }
        if (failure === "unregister") throw Error("synthetic-private-unregister");
      };
    },
    subscribe(fn) {
      trace.push("subscribe");
      if (failure === "subscribe") throw Error("synthetic-private-subscribe");
      listeners.add(fn);
      return () => {
        trace.push("unsubscribe-scenes"); listeners.delete(fn);
        if (failure === "unsubscribe-scenes") throw Error("synthetic-private-unsubscribe");
      };
    },
    open(id) {
      trace.push("open");
      if (failure === "open-throw") throw Error("synthetic-private-open");
      if (failure === "open-false") return false;
      active = rows.get(id); emit(); return active !== undefined;
    },
    close() {
      trace.push("close"); active = undefined; emit();
      if (failure === "close") throw Error("synthetic-private-close");
    },
  };
  const ctx = { tuiScenes: scenes, effect(fn) {
    trace.push("effect");
    const cleanup = fn();
    if (typeof cleanup === "function") effects.push(cleanup);
    if (failure === "effect") throw Error("synthetic-private-effect");
    if (failure === "effect-immediate") cleanup?.();
  } };
  Object.defineProperty(ctx, "root", { get() { throw Error("private root forbidden"); } });
  return { ctx, scenes, rows, effects, trace,
    replace() { active = { id: "another-scene" }; emit(); },
    resetActive(row) { active = row; },
    runEffects() { for (const fn of effects) fn(); } };
}

function channelHarness({ cleanupThrows = false } = {}) {
  let listener;
  let live = true;
  let stops = 0;
  const values = { version: 1, ready: true, startupFailure: undefined, status: "idle",
    sessionRef: { backendId: "dsh", sessionId: "actual-session" }, sessionId: "actual-session",
    cwd: "/synthetic/actual", agentBindingGeneration: 1 };
  const channel = {};
  for (const key of Object.keys(values)) Object.defineProperty(channel, key, { get() {
    if (!live) throw Error("synthetic-private-owner-ended");
    return values[key];
  } });
  for (const key of ["rows", "body", "trace", "history"]) Object.defineProperty(channel, key, { get() { throw Error("body forbidden"); } });
  channel.subscribe = fn => {
    listener = fn;
    return () => { stops++; if (cleanupThrows) throw Error("synthetic-private-cleanup"); };
  };
  return { channel, values, notify() { listener?.(); }, revoke() { live = false; }, stops: () => stops };
}

function renderer(component, channel) {
  let effect;
  let previousDeps;
  let cleanup;
  let hookCalls = 0;
  let elements = 0;
  const Text = Symbol("host-text");
  const React = {
    useEffect(fn, deps) {
      hookCalls++;
      if (!previousDeps || deps.some((value, index) => value !== previousDeps[index])) effect = { fn, deps };
    },
    createElement(type, props, ...children) { elements++; return { type, props, children }; },
  };
  function render(next = channel) {
    const element = component({ React, ui: { Text }, channel: next, close() { throw Error("props.close bypass forbidden"); } });
    if (effect) {
      cleanup?.();
      previousDeps = effect.deps;
      const fn = effect.fn; effect = undefined;
      cleanup = fn();
    }
    return element;
  }
  return { render, unmount() { cleanup?.(); cleanup = undefined; }, Text,
    calls: () => ({ hooks: hookCalls, elements }) };
}

function install(host, handlers = {}) {
  const observations = [];
  const unavailable = [];
  const control = installObservationScene(host.ctx, {
    onObservation: value => { observations.push(value); return handlers.observation?.(value); },
    onUnavailable: value => { unavailable.push(value); return handlers.unavailable?.(value); },
  });
  const descriptor = [...host.rows.values()][0];
  return { control, observations, unavailable, descriptor };
}

test("registers synchronously, scopes cleanup and opens via public scenes", async () => {
  const host = scenesHarness(); const value = install(host);
  assert.equal(host.scenes.active, value.descriptor);
  assert.ok(host.trace.indexOf("effect") < host.trace.indexOf("open"));
  const channel = channelHarness(); const view = renderer(value.descriptor.component, channel.channel);
  const element = view.render();
  assert.equal(element.type, view.Text);
  assert.ok(element.children.some(text => typeof text === "string" && text.includes("核对")));
  assert.deepEqual(view.calls(), { hooks: 1, elements: 1 });
  assert.deepEqual(value.observations, []);
  await settle();
  assert.equal(value.observations[0].kind, "foreground-observed");
  assert.equal(value.observations[0].cwd, "/synthetic/actual");
  assert.equal(Object.hasOwn(value.observations[0], "loaded"), false);
  value.control.close();
  assert.equal(channel.stops(), 1);
  assert.deepEqual(value.unavailable, []);
  assert.equal(host.scenes.active, undefined);
  host.runEffects(); value.control.dispose(); view.unmount(); await settle();
  assert.equal(channel.stops(), 1);
});

test("early close cancels deferred observations and late callbacks", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  const view = renderer(value.descriptor.component, channel.channel); view.render();
  value.control.close(); channel.notify(); view.unmount(); await settle();
  assert.deepEqual(value.observations, []);
  assert.deepEqual(value.unavailable, [{ kind: "unknown", reason: "closed-before-observation" }]);
  assert.equal(channel.stops(), 1);
});

test("replacement terminates observation and never closes the other scene", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  renderer(value.descriptor.component, channel.channel).render();
  host.replace(); value.control.close(); channel.notify(); await settle();
  assert.equal(host.scenes.active.id, "another-scene");
  assert.equal(host.trace.includes("close"), false);
  assert.equal(value.unavailable[0].reason, "scene-replaced");
  assert.deepEqual(value.observations, []);
  assert.equal(channel.stops(), 1);
});

test("unmount reports unavailable and retained notifications stay stopped", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  const view = renderer(value.descriptor.component, channel.channel); view.render(); view.unmount();
  channel.notify(); await settle();
  assert.equal(value.unavailable[0].reason, "scene-unmounted");
  assert.equal(value.observations.length, 0);
  assert.equal(channel.stops(), 1);
});

test("channel replacement ends the installation rather than continuing one run", async () => {
  const host = scenesHarness(); const value = install(host); const first = channelHarness(); const second = channelHarness();
  const view = renderer(value.descriptor.component, first.channel); view.render(); await settle();
  view.render(second.channel); first.notify(); second.notify(); await settle();
  assert.equal(first.stops(), 1);
  assert.equal(second.stops(), 0);
  assert.equal(value.unavailable[0].reason, "channel-changed");
  assert.equal(value.observations.length, 1);
});

test("owner revocation produces fixed unavailable and cleans observer", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  renderer(value.descriptor.component, channel.channel).render(); channel.revoke(); await settle();
  assert.equal(value.unavailable[0].reason, "observation-unavailable");
  assert.equal(channel.stops(), 1);
  assert.equal(JSON.stringify(value).includes("synthetic-private"), false);
});

for (const [failure, reason] of [
  ["register", "registration-failed"], ["effect", "installation-failed"],
  ["subscribe", "installation-failed"], ["open-throw", "open-failed"], ["open-false", "open-failed"],
]) test(`${failure} failure is sanitized and leaves no registration`, async () => {
  const host = scenesHarness(failure); const value = install(host);
  assert.deepEqual(value.unavailable, [{ kind: "unknown", reason }]);
  assert.equal(host.rows.size, 0);
  value.control.close(); value.control.dispose(); host.runEffects(); await settle();
  assert.equal(value.unavailable.length, 1);
  assert.equal(JSON.stringify(value.unavailable).includes("synthetic-private"), false);
});

for (const failure of ["unregister", "unsubscribe-scenes", "close", "observer"]) {
  test(`${failure} cleanup failure cannot skip remaining cleanup`, async () => {
    const host = scenesHarness(failure); const value = install(host);
    const channel = channelHarness({ cleanupThrows: failure === "observer" });
    renderer(value.descriptor.component, channel.channel).render(); await settle();
    assert.doesNotThrow(() => value.control.close());
    assert.equal(host.rows.size, 0);
    assert.ok(host.trace.includes("unregister"));
    assert.ok(host.trace.includes("unsubscribe-scenes"));
    assert.ok(host.trace.includes("close"));
    assert.equal(channel.stops(), 1);
    assert.equal(value.unavailable[0].reason, "cleanup-failed");
    assert.doesNotThrow(() => value.control.dispose());
  });
}

test("consumer callback errors are fixed failures and never escape asynchronously", async () => {
  const host = scenesHarness();
  const value = install(host, { observation() { throw Error("synthetic-private-consumer"); },
    unavailable() { throw Error("synthetic-private-reporter"); } });
  const channel = channelHarness(); renderer(value.descriptor.component, channel.channel).render();
  await settle();
  assert.equal(value.unavailable[0].reason, "callback-failed");
  assert.equal(channel.stops(), 1);
  assert.equal(JSON.stringify(value.unavailable).includes("synthetic-private"), false);
});

test("same context rejects a second live installation and allows one after disposal", () => {
  const host = scenesHarness(); const first = install(host); const second = install(host);
  assert.equal(host.rows.size, 1);
  assert.equal(second.unavailable[0].reason, "duplicate-installation");
  first.control.dispose();
  const third = install(host);
  assert.equal(third.unavailable.length, 0);
  assert.equal(host.rows.size, 1);
  third.control.dispose();
});

test("concurrent mounts terminate both instead of duplicating observers", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  const first = renderer(value.descriptor.component, channel.channel); first.render();
  const second = renderer(value.descriptor.component, channel.channel); second.render();
  await settle();
  assert.equal(value.unavailable[0].reason, "multiple-mounts");
  assert.equal(channel.stops(), 1);
  assert.equal(value.observations.length, 0);
  first.unmount(); second.unmount();
});

test("waiting metadata does not make an early close successful", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  channel.values.ready = false; channel.values.status = "starting";
  renderer(value.descriptor.component, channel.channel).render(); await settle();
  assert.equal(value.observations[0].kind, "waiting");
  value.control.close();
  assert.equal(value.unavailable[0].reason, "closed-before-observation");
});

test("ctx effect disposal before mount makes retained component inert", async () => {
  const host = scenesHarness(); const value = install(host); const channel = channelHarness();
  host.runEffects();
  renderer(value.descriptor.component, channel.channel).render(); await settle();
  assert.equal(value.unavailable[0].reason, "scene-disposed");
  assert.equal(value.observations.length, 0);
  assert.equal(channel.stops(), 0);
});

test("rejected observation callback is contained with a fixed reason", async () => {
  const host = scenesHarness();
  const value = install(host, { observation: async () => { throw Error("synthetic-private-async-observation"); } });
  const channel = channelHarness(); renderer(value.descriptor.component, channel.channel).render();
  await settle();
  assert.equal(value.unavailable[0].reason, "callback-failed");
  assert.equal(channel.stops(), 1);
});

test("rejected unavailable callback cannot become an unhandled rejection", async () => {
  const host = scenesHarness();
  const value = install(host, { unavailable: async () => { throw Error("synthetic-private-async-unavailable"); } });
  value.control.close(); await settle();
  assert.equal(value.unavailable[0].reason, "closed-before-observation");
});

test("public effect harness executes factory now and retains only its returned cleanup", () => {
  const host = scenesHarness();
  let started = 0; let stopped = 0;
  host.ctx.effect(() => { started++; return () => { stopped++; }; });
  assert.equal(started, 1);
  assert.equal(stopped, 0);
  host.runEffects();
  assert.equal(started, 1);
  assert.equal(stopped, 1);
  assert.throws(() => host.ctx.effect(() => { throw Error("synthetic-factory-failure"); }), /synthetic-factory-failure/);
});

test("immediate owner disposal during effect registration prevents opening", async () => {
  const host = scenesHarness("effect-immediate"); const value = install(host);
  assert.equal(host.rows.size, 0);
  assert.equal(host.trace.includes("open"), false);
  assert.equal(host.trace.includes("subscribe"), false);
  assert.equal(value.unavailable[0].reason, "scene-disposed");
  host.runEffects(); value.control.dispose(); await settle();
  assert.equal(value.unavailable.length, 1);
});
