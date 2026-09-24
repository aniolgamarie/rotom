import { test, assert, evidence } from "./recorded-test.ts";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { isHumanTerminalInput } from "../src/adapters/terminal-input.ts";
import { Store } from "../src/store/database.ts";
import type { RecoveryRecord } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

test("[U T36] terminal capability replies are not human input, including mixed reply/key batches", () => {
  const replies = ["\x1b[?1;2c", "\x1b[?1u", "\x1b[4;900;1200t", "\x1b[1;1R", "\x1b]11;rgb:ffff/ffff/ffff\x07", "\x1b[I", "\x1bPdevice-reply\x1b\\", "\x1b]10;rgb:0000/0000/0000\x1b\\"];
  for (const input of replies) {
    assert.equal(isHumanTerminalInput(input), false);
    assert.equal(isHumanTerminalInput(`${input}x`), true); assert.equal(isHumanTerminalInput(`x${input}`), true);
  }
  assert.equal(isHumanTerminalInput(replies.join("")), false);
  for (const input of ["x", "\x1b", "\x03", "\r", "\x1b[A", "\x1b[97u", "\x1b[200~paste\x1b[201~"]) assert.equal(isHumanTerminalInput(input), true);
});

for (const variant of ["continue", "human-key", "terminal-replies", "reload"] as const) test(`[A/E Q2 ${variant === "terminal-replies" ? "T36 REC-020" : variant === "reload" ? "REC-020 T37" : ""}] real Pi PTY ${variant} respects waiting and raw human input`, { timeout: 30000 }, async (t) => {
  const root = isolatedDirectory(t), agentDir = join(root, "agent"), cwd = join(root, "workspace"); mkdirSync(agentDir); mkdirSync(cwd);
  let requests = 0;
  const server = createServer((req, res) => { req.resume(); req.on("end", () => {
    requests++;
    if (requests === 1) { res.writeHead(429, { "content-type": "application/json", "retry-after": "1" }); res.end('{"error":{"message":"fixture limit","code":"rate_limit"}}'); return; }
    res.writeHead(200, { "content-type": "text/event-stream" });
    for (const choice of [{ index: 0, delta: { role: "assistant", content: "Done" }, finish_reason: null }, { index: 0, delta: {}, finish_reason: "stop" }])
      res.write(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", created: 1, model: "fixture-model", choices: [choice] })}\n\n`);
    res.end("data: [DONE]\n\n");
  }); });
  await listenLoopback(server); const port = (server.address() as { port: number }).port;
  writeFileSync(join(agentDir, "models.json"), JSON.stringify({ providers: { "fixture-provider": { baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "fixture-only", api: "openai-completions", models: [{ id: "fixture-model", name: "Fixture", reasoning: false, input: ["text"], contextWindow: 32000, maxTokens: 1000, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } }));
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [], compaction: { enabled: false }, retry: { enabled: false, provider: { maxRetries: 0 } }, enableInstallTelemetry: false, quietStartup: true }));
  const config = configured(); config.storage.path = join(root, "state/runtime.db"); config.recovery.requestTimeoutMs = 10000;
  if (variant === "reload") config.quotaGroups.pool.baseIntervalMs = 5000;
  const configPath = join(root, "task-keeper.json"); writeFileSync(configPath, JSON.stringify(config));
  const pkg = fileURLToPath(new URL("..", import.meta.url));
  const argv = [process.execPath, join(pkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"), "--no-extensions", "-e", join(pkg, "index.ts"), "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline", "--provider", "fixture-provider", "--model", "fixture-model", "--thinking", "off", "--tools", "read,write,edit", "--session-dir", join(root, "sessions")];
  const command = argv.map((arg) => "'" + arg.replace(/'/g, "'\\''") + "'").join(" ");
  const child = spawn("/bin/script", ["-q", "-e", "-c", command, "/dev/null"], { cwd, detached: true, stdio: ["pipe", "pipe", "pipe"], env: {
    PATH: process.env.PATH, TERM: "xterm-256color", LANG: "C.UTF-8", PI_CODING_AGENT_DIR: agentDir, PI_TASK_KEEPER_CONFIG: configPath, PI_OFFLINE: "1", PI_TELEMETRY: "0",
  } });
  let output = "", store: Store | undefined;
  child.stdout.on("data", (data) => { output = (output + data).slice(-12000); }); child.stderr.on("data", (data) => { output = (output + data).slice(-12000); });
  t.after(async () => { store?.close(); if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGTERM"); await exit; }
    server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve())); });
  async function wait(predicate: () => boolean) {
    const deadline = Date.now() + 15000;
    while (!predicate()) { if (Date.now() > deadline || child.exitCode !== null) throw new Error(JSON.stringify({ requests, output })); await delay(20); }
  }
  await wait(() => existsSync(config.storage.path + ".identity")); store = new Store(join(root, "state"));
  await delay(300); child.stdin.write("Run the synthetic fixture\r");
  await wait(() => store!.list<RecoveryRecord>("recovery")[0]?.value.status === "WAITING_QUOTA");
  const before = store.list<RecoveryRecord>("recovery")[0].value, ownerBefore = store.owner(before.scopeId)!;
  if (variant === "reload") {
    child.stdin.write("/reload\r");
    await wait(() => store!.owner(before.scopeId)!.epoch > ownerBefore.epoch && output.includes("Reloaded"));
    await delay(Math.max(0, before.notBefore - Date.now()) + 300);
    const after = store.list<RecoveryRecord>("recovery")[0].value;
    for (const id of ["REC-020", "T37"]) evidence(id, () => {
      assert.equal(after.status, "PAUSED"); assert.equal(after.sessionId, before.sessionId); assert.equal(after.attempts, 0);
      assert.deepEqual(after.history, before.history); assert.equal(after.notBefore, before.notBefore); assert.equal(requests, 1);
      assert.ok(store!.owner(before.scopeId)!.epoch > ownerBefore.epoch); assert.equal(after.intentId, null); assert.deepEqual(store!.claims(), []);
    });
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"lifecycle-observers");mkdirSync(path,{recursive:true});
      writeFileSync(join(path,"pty-reload.json"),JSON.stringify({before,after,ownerBefore,ownerAfter:store.owner(before.scopeId),requests,output},null,2)); }
  } else if (variant === "human-key") {
    child.stdin.write("x"); await wait(() => store!.list<RecoveryRecord>("recovery")[0]?.value.status === "PAUSED"); await delay(1200);
    assert.equal(requests, 1); assert.equal(store.list<RecoveryRecord>("recovery")[0].value.reason, "user_terminal_input");
  } else {
    if (variant === "terminal-replies") child.stdin.write("\x1b[?1;2c\x1b[1;1R\x1b]11;rgb:ffff/ffff/ffff\x07\x1b[I");
    await wait(() => store!.list<RecoveryRecord>("recovery")[0]?.value.status === "DONE"); assert.equal(requests, 2);
    assert.equal(store.list<RecoveryRecord>("recovery")[0].value.attempts, 1);
    if (variant === "terminal-replies") for (const id of ["T36", "REC-020"]) evidence(id, () => {
      const after = store!.list<RecoveryRecord>("recovery")[0].value;
      assert.notEqual(after.reason, "user_terminal_input"); assert.equal(after.status, "DONE"); assert.equal(after.attempts, 1);
      assert.equal(after.scopeId, before.scopeId); assert.equal(after.sessionId, before.sessionId); assert.equal(requests, 2);
      assert.equal(existsSync(join(cwd,"proof.txt")),false);
    });
  }
});
