import { test, assert, evidence, matrixCase, acceptance, observerArtifact } from "./recorded-test.ts";
import { spawn, execFileSync, fork } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { DatabaseSync } from "node:sqlite";
import { businessDigest } from "../src/store/maintenance.ts";
import { DEFAULT_CONFIG } from "../src/config.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

for (const transition of ["upgrade", "disable", "restart", "rollback"] as const)
test(`[P E T76] ${transition} preserves every lifecycle send fact through actual Pi loading`, { timeout: 45000 }, async t => {
  const root = isolatedDirectory(t), agentDir = join(root, "agent"), cwd = join(root, "workspace"), state = join(root, "state");
  mkdirSync(agentDir); mkdirSync(cwd); writeFileSync(join(cwd, "retained.txt"), "unchanged workspace");
  let received = 0; const server = createServer((req, res) => { received++; req.resume(); res.end("unexpected request"); });
  await listenLoopback(server); t.after(() => { server.closeAllConnections(); server.close(); });
  const pkg = fileURLToPath(new URL("..", import.meta.url));
  writeFileSync(join(agentDir, "models.json"), JSON.stringify({ providers: { "fixture-provider": { api: "openai-completions", baseUrl: `http://127.0.0.1:${(server.address() as {port:number}).port}/v1`, apiKey: "fixture-key", models: [{ id: "fixture-model", name: "Fixture", reasoning: false, input: ["text"], contextWindow: 32000, maxTokens: 1000, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } }));
  const authPath = join(agentDir, "auth.json"), auth = JSON.stringify({ "fixture-provider": { type: "api_key", key: "private-fixture-key" } }); writeFileSync(authPath, auth, { mode: 0o600 });
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [], enableInstallTelemetry: false, compaction: { enabled: false } }));
  const initial = new Store(state), owner = initial.claimOwner("preserved", "owner");
  for (const fact of ["not-sent", "terminal-confirmed", "unknown"] as const) {
    initial.prepare(owner, `${fact}-intent`, "write", { workspace: cwd, fact }, [{ id: `writer-${fact}`, capacity: 1, units: 1 }]);
    initial.reserveRequest(owner, `${fact}-intent`, `${fact}-request`, [{ id: "budget", ceiling: 12 }]);
    if (fact === "terminal-confirmed") { initial.markSent(owner, `${fact}-intent`); initial.acknowledge(`${fact}-intent`, "native-completed"); }
    initial.settleRequest(`${fact}-request`, fact === "terminal-confirmed" ? "sent" : fact === "not-sent" ? "not_sent" : "unknown");
    initial.settle(`${fact}-intent`, fact === "terminal-confirmed" ? "terminated" : fact === "not-sent" ? "not_sent" : "unknown");
  }
  initial.revokeOwner(owner);
  initial.put("recovery", "preserved", { status: "WAITING_QUOTA", notBefore: 9999999999999, attempts: 3, history: ["preserved"] });
  const before = businessDigest(initial.db);
  if (transition === "upgrade" || transition === "rollback") initial.db.exec("DROP TABLE maintenance_history; PRAGMA user_version=1");
  initial.close();
  const maintenance = (action: string) => JSON.parse(execFileSync(process.execPath, ["--experimental-strip-types", join(pkg, "scripts/state-maintenance.ts"), action, state], { encoding: "utf8", env: { ...process.env, NODE_NO_WARNINGS: "1" } }));
  if (transition === "upgrade") assert.equal(maintenance("upgrade").version, 3);
  if (transition === "rollback") {
    const migration = fork(join(pkg, "tests/fixtures/maintenance-worker.ts"), [state, "committed"], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] });
    t.after(() => migration.kill("SIGKILL"));
    assert.equal((await once(migration, "message"))[0].type, "ready");
    const reached = once(migration, "message"); migration.send("go"); assert.equal((await reached)[0].type, "cut");
    const exited = once(migration, "exit"); migration.kill("SIGKILL"); await exited;
    assert.equal(maintenance("rollback").version, 1);
  }
  const configPath = join(root, "task-keeper.json");
  for (const enabled of transition === "disable" ? [true, false, true] : [true, true]) {
    const config = { ...structuredClone(DEFAULT_CONFIG), enabled, storage: { path: join(state, "runtime.db") } };
    const policy = JSON.stringify(config); writeFileSync(configPath, policy);
    const child = spawn(process.execPath, [join(pkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"), "--mode", "rpc", "--no-extensions", "-e", join(pkg, "index.ts"), "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline", "--provider", "fixture-provider", "--model", "fixture-model", "--no-tools", "--session-dir", join(root, "sessions")], {
      cwd, env: { PATH: process.env.PATH, PI_CODING_AGENT_DIR: agentDir, PI_TASK_KEEPER_CONFIG: configPath, PI_OFFLINE: "1", PI_TELEMETRY: "0" }, stdio: ["pipe", "pipe", "pipe"],
    });
    let output = "", pending = "";
    const responses = new Map<string, () => void>();
    child.stdout.on("data", chunk => { output += chunk; pending += chunk; let end: number; while ((end = pending.indexOf("\n")) >= 0) {
      const line = pending.slice(0, end); pending = pending.slice(end + 1); try { const value = JSON.parse(line); responses.get(value.id)?.(); } catch {}
    } });
    const request = (id: string, message?: string) => new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(output)), 10000);
      responses.set(id, () => { clearTimeout(timer); responses.delete(id); resolve(); });
      child.stdin.write(JSON.stringify(message ? { id, type: "prompt", message } : { id, type: "get_state" }) + "\n");
    });
    try { await request("state"); await request("doctor", "/orch doctor"); await request("init", "/orch init"); }
    finally { if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGTERM"); await exit; } }
    const current = new DatabaseSync(join(state, "runtime.db"));
    try {
      assert.equal(businessDigest(current), before);
      assert.equal(current.prepare("PRAGMA user_version").get()!.user_version, transition === "rollback" ? 1 : 3);
      for (const [fact, status, requestState, claims] of [
        ["not-sent", "not_sent", "not_sent", 0], ["terminal-confirmed", "settled", "sent", 0], ["unknown", "unknown", "unknown", 1],
      ] as const) matrixCase("lifecycle-preservation", `${transition}.${fact}`, () => evidence("T76", () => {
        const intent = current.prepare("SELECT * FROM intents WHERE id=?").get(`${fact}-intent`)!;
        assert.equal(intent.status, status); assert.equal(JSON.parse(String(intent.payload)).workspace, cwd);
        assert.equal(current.prepare("SELECT state FROM requests WHERE id=?").get(`${fact}-request`)!.state, requestState);
        assert.equal(current.prepare("SELECT count(*) n FROM claims WHERE intent_id=?").get(`${fact}-intent`)!.n, claims);
        assert.equal(current.prepare("SELECT used FROM buckets WHERE id='budget'").get()!.used, 1);
        assert.equal(current.prepare("SELECT reserved FROM buckets WHERE id='budget'").get()!.reserved, 1);
        assert.equal(readFileSync(join(cwd, "retained.txt"), "utf8"), "unchanged workspace");
      }));
    } finally { current.close(); }
    if (transition === "rollback") assert.ok(output.includes("DATABASE_MIGRATION_REQUIRED"), output);
    assert.equal(readFileSync(configPath, "utf8"), policy); assert.equal(readFileSync(authPath, "utf8"), auth);
    assert.equal(readFileSync(join(cwd, "retained.txt"), "utf8"), "unchanged workspace"); assert.equal(received, 0);
  }
  for(const variant of transition === "disable"?["disabled-load","init-existing"]:["init-existing"])acceptance("AC35",variant,{level:"E",observer:"real-Pi-load-init-exit-with-existing-state",predicate:variant,artifact:observerArtifact(`load-${transition}-${variant}`,{transition,before,received})},()=>{const observer=new DatabaseSync(join(state,"runtime.db"));try{assert.equal(businessDigest(observer),before);assert.equal(received,0);assert.equal(readFileSync(authPath,"utf8"),auth);assert.equal(readFileSync(join(cwd,"retained.txt"),"utf8"),"unchanged workspace");}finally{observer.close();}});
});
