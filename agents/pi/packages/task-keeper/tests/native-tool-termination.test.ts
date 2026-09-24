import { test, assert } from "./recorded-test.ts";
import { createFindTool, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { mkdirSync, writeFileSync, readFileSync, watch, existsSync } from "node:fs";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { PiInteractiveAdapter } from "../src/adapters/pi-interactive.ts";
import { childPhysicallyStopped, type ChildObservation } from "../src/adapters/child-contract.ts";
import { processIdentity, originalProcessStopped } from "../src/adapters/process-identity.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[A P EXE-011] native find cancellation leaves a live process and interactive termination stays unknown", { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t), bin = join(root, "bin"), marker = join(root, "find-ready.json"); mkdirSync(bin);
  writeFileSync(join(bin, "fd"), `#!${process.execPath}
const fs=require('node:fs');if(process.argv.includes('--version'))process.exit(0);
process.on('SIGTERM',()=>{});fs.writeFileSync(${JSON.stringify(marker + ".tmp")},JSON.stringify({pid:process.pid}));fs.renameSync(${JSON.stringify(marker + ".tmp")},${JSON.stringify(marker)});setInterval(()=>{},1000);
`, { mode: 0o700 });
  const savedPath = process.env.PATH; process.env.PATH = `${bin}:${savedPath}`;
  t.after(() => { process.env.PATH = savedPath; });
  let ready!: () => void; const started = new Promise<void>(resolve => { ready = resolve; });
  const watcher = watch(root, () => { if (existsSync(marker)) ready(); }); t.after(() => watcher.close());
  const config = configured(); config.executionProfiles.interactive.tools = ["find"];
  const pi = { getAllTools: () => [{ name: "find", sourceInfo: { source: "builtin" } }], getActiveTools: () => ["find"], getThinkingLevel: () => "off" } as unknown as ExtensionAPI;
  const ctx = { mode: "rpc", isIdle: () => true, hasPendingMessages: () => false,
    sessionManager: { getSessionId: () => "session", getLeafId: () => "leaf", getSessionFile: () => "session.jsonl" } } as unknown as ExtensionContext;
  const adapter = new PiInteractiveAdapter(pi, config, ctx); t.after(() => adapter.dispose());
  const cancellation = new AbortController(); adapter.toolStarted("find-call", "find");
  const pending = createFindTool(root).execute("find-call", { pattern: "*" }, cancellation.signal);
  await Promise.race([started, pending.then(() => { throw new Error("find completed before its barrier"); })]);
  const identity = processIdentity(JSON.parse(readFileSync(marker, "utf8")).pid); assert.ok(identity);
  t.after(() => { if (originalProcessStopped(identity) === false) process.kill(identity.pid, "SIGKILL"); });
  assert.equal(adapter.snapshot().terminationKnown, false);
  const rejected = assert.rejects(pending, /abort/i); cancellation.abort(); await rejected;
  assert.equal(originalProcessStopped(identity), false);
  adapter.toolEnded("find-call", true);
  assert.equal(adapter.snapshot().terminationKnown, false);
  assert.ok(adapter.snapshot().blockedReasons.includes("external_tool_lifecycle_unknown"));
});

test("[P T41] a dead reporter does not prove an active or unobserved external tool stopped", async t => {
  const child = spawn(process.execPath, ["-e", "console.log('ready');process.stdin.once('data',()=>process.exit(0));"], { stdio: ["pipe", "pipe", "pipe"] });
  t.after(() => child.kill("SIGKILL")); await once(child.stdout, "data");
  const identity = processIdentity(child.pid!)!; assert.ok(identity);
  const observation = { process: identity, externalWork: [] } as unknown as ChildObservation;
  assert.equal(childPhysicallyStopped(observation), false);
  const closed = once(child, "close"); child.stdin.end("exit"); await closed;
  assert.equal(originalProcessStopped(identity), true); assert.equal(childPhysicallyStopped(observation), true);
  assert.equal(childPhysicallyStopped({ ...observation, externalWork: ["find-still-running"] }), false);
  assert.equal(childPhysicallyStopped({ ...observation, externalWork: ["grep-in-progress"] }), false);
  assert.equal(childPhysicallyStopped({ ...observation, externalWork: undefined }), false);
});
