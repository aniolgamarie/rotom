import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, writeFile, rm, symlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { queryMetadata, queryFromRuntime } from "../../agents/dsh/templates/session-metadata.mjs";

const snapshot = () => ({ header: { id: "synthetic-session", cwd: "/synthetic/project",
  createdAt: "2026-01-01", title: "synthetic-private-title" }, revision: "synthetic-revision",
  eventCount: 7, sizeBytes: 100, extra: "synthetic-private-body" });

function fixture(value = snapshot(), failure) {
  const calls = [];
  const JsonlSessionPersistence = {};
  class Context {
    fiber = { dispose: async () => {
      calls.push("dispose");
      if (failure === "dispose") throw Error("synthetic-private-error");
    } };
    sessionPersistence = {
      stat: async id => {
        calls.push(["stat", id]);
        if (failure === "stat") throw Error("synthetic-private-error");
        return value;
      },
      open: () => assert.fail("metadata query must not open a session handle"),
      create: () => assert.fail("metadata query must not create a session"),
      list: () => assert.fail("an explicit ID must not query every session header"),
    };
    async plugin(plugin, config) {
      assert.equal(plugin, JsonlSessionPersistence);
      calls.push(["plugin", config]);
      if (failure === "plugin") throw Error("synthetic-private-error");
    }
  }
  return { calls, api: { Context, JsonlSessionPersistence, SessionId: id => id } };
}

test("only public stat is used with the exact root and ID; private fields never leave", async () => {
  const fake = fixture();
  const result = await queryMetadata(fake.api, "/synthetic/native-home/sessions", "synthetic-session");
  assert.deepEqual(fake.calls, [["plugin", { root: "/synthetic/native-home/sessions" }],
    ["stat", "synthetic-session"], "dispose"]);
  assert.deepEqual(result, { status: "metadata", session_id: "synthetic-session",
    cwd: "/synthetic/project", source: "session-persistence-stat" });
  assert.equal(JSON.stringify(result).includes("private"), false);
  assert.equal(Object.hasOwn(result, "loaded"), false);
  assert.equal(Object.hasOwn(result, "run_id"), false);
  assert.equal(Object.hasOwn(result, "writer"), false);
});

for (const [label, value] of [["absent", undefined], ["null", null], ["empty", {}],
  ["wrong-id", { header: { id: "other", cwd: "/synthetic/project" } }],
  ["no-cwd", { header: { id: "synthetic-session" } }],
  ["relative-cwd", { header: { id: "synthetic-session", cwd: "relative" } }],
  ["nul-cwd", { header: { id: "synthetic-session", cwd: "/synthetic/\0project" } }],
  ["traversal-cwd", { header: { id: "synthetic-session", cwd: "/synthetic/../project" } }]]) {
  test(label + " remains unavailable; no absence or load claim", async () => {
    const fake = fixture(null);
    const api = fake.api;
    const Original = api.Context;
    api.Context = class extends Original { constructor() { super(); this.sessionPersistence.stat = async () => value; } };
    assert.deepEqual(await queryMetadata(api, "/synthetic/sessions", "synthetic-session"), { status: "unavailable" });
    assert.equal(fake.calls.at(-1), "dispose");
  });
}

for (const failure of ["plugin", "stat", "dispose"]) {
  test(failure + " failure is sanitized and cleaned up", async () => {
    const fake = fixture(snapshot(), failure);
    const result = await queryMetadata(fake.api, "/synthetic/sessions", "synthetic-session");
    assert.deepEqual(result, { status: "unavailable" });
    assert.equal(fake.calls.at(-1), "dispose");
  });
}

for (const [root, id] of [["relative", "session"], ["/synthetic/../sessions", "session"],
  ["/synthetic/sessions", "--resume"], ["/synthetic/sessions", "../session"], ["/synthetic/sessions", ""],
  ["/synthetic/sessions", "session\n"], ["/synthetic/sessions", "session\r"]]) {
  test("invalid target refuses before mounting: " + JSON.stringify([root, id]), async () => {
    const fake = fixture();
    assert.deepEqual(await queryMetadata(fake.api, root, id), { status: "unavailable" });
    assert.deepEqual(fake.calls, []);
  });
}

async function packages(directory) {
  const sources = {
    cordis: 'export class Context { fiber = { dispose: async () => {} }; async plugin(p, c) { await p.apply(this, c); } }',
    "dsh-session": 'export const SessionId = id => id;',
    "dsh-session-persistence-jsonl": 'export function apply(ctx, config) { ctx.sessionPersistence = { stat: async id => ({ header: { id, cwd: config.root }, extra: "synthetic-private" }) }; }',
  };
  for (const [name, code] of Object.entries(sources)) {
    const root = path.join(directory, "node_modules/@deepseek-ai", name);
    await mkdir(root, { recursive: true, mode: 0o700 });
    await writeFile(path.join(root, "package.json"), JSON.stringify({ type: "module", exports: "./index.mjs" }), { mode: 0o600 });
    await writeFile(path.join(root, "index.mjs"), code, { mode: 0o600 });
  }
}

test("runtime resolution uses only the selected public package exports", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "rotom-metadata-fake-"));
  try {
    await packages(root);
    const result = await queryFromRuntime(root, "/synthetic/sessions", "synthetic-session");
    assert.deepEqual(result, { status: "metadata", session_id: "synthetic-session",
      cwd: "/synthetic/sessions", source: "session-persistence-stat" });
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("parent package fallback cannot substitute a missing runtime dependency", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "rotom-metadata-parent-"));
  try {
    await packages(root);
    const child = path.join(root, "candidate");
    await mkdir(path.join(child, "node_modules"), { recursive: true, mode: 0o700 });
    assert.deepEqual(await queryFromRuntime(child, "/synthetic/sessions", "synthetic-session"), { status: "unavailable" });
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("linked package outside the selected modules root is rejected", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "rotom-metadata-linked-"));
  try {
    const external = path.join(root, "external");
    const candidate = path.join(root, "candidate");
    await packages(external);
    await mkdir(path.join(candidate, "node_modules/@deepseek-ai"), { recursive: true, mode: 0o700 });
    await symlink(path.join(external, "node_modules/@deepseek-ai/cordis"),
      path.join(candidate, "node_modules/@deepseek-ai/cordis"));
    assert.deepEqual(await queryFromRuntime(candidate, "/synthetic/sessions", "synthetic-session"), { status: "unavailable" });
  } finally { await rm(root, { recursive: true, force: true }); }
});
