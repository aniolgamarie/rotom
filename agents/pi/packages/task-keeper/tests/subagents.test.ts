import { writerParentCut } from "./fixtures/writer-parent-cut.ts";
import { settlementReplay } from "./fixtures/settlement-replay.ts";
import { thinkingCut } from "./fixtures/thinking-cut.ts";
import { test, assert, evidence, matrixCase, acceptance, observerArtifact } from "./recorded-test.ts";
import { spawn } from "node:child_process";
import { createServer, type ServerResponse } from "node:http";
import { once } from "node:events";
import { mkdirSync, writeFileSync, readFileSync, existsSync, symlinkSync, watch } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { processIdentity, originalProcessStopped } from "../src/adapters/process-identity.ts";
import { guardedPath } from "../src/adapters/child-reporter.ts";
import { childGateCut } from "./fixtures/child-gate-cut.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

test("guarded tools reject lexical/symlink escape and repository metadata writes", (t) => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"); mkdirSync(cwd);
  symlinkSync(root, join(cwd, "escape"));
  for (const path of ["../outside", ".git/config", "escape/outside", "~/outside", "@outside"]) assert.throws(() => guardedPath(cwd, path, true));
  assert.equal(guardedPath(cwd, "new/nested.cpp", true), join(cwd, "new/nested.cpp"));
});

function answer(res: ServerResponse, tool: boolean, outside: boolean, inputTokens = 10, find = false, responseModel: string | null = "fixture-model") {
  res.writeHead(200, { "content-type": "text/event-stream" });
  const delta = tool ? { role: "assistant", tool_calls: [{ index: 0, id: "call-write", type: "function",
    function: { name: find ? "tk_find" : "tk_write", arguments: JSON.stringify(find ? { pattern: "*" } : { path: outside ? "../escaped.txt" : "candidate.txt", content: "guarded\n" }) } }] }
    : { role: "assistant", content: "Bounded fixture finished. Parent verification remains required." };
  for (const choice of [{ index: 0, delta, finish_reason: null }, { index: 0, delta: {}, finish_reason: tool ? "tool_calls" : "stop" }]) {
    res.write(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", created: 1, ...(responseModel === null ? {} : { model: responseModel }), choices: [choice], usage: { prompt_tokens: inputTokens, completion_tokens: 10, total_tokens: inputTokens + 10 } })}\n\n`);
  }
  res.end("data: [DONE]\n\n");
}

for (const variant of ["writers-disabled", "writers-disabled-child","protected-gate-unavailable", "protected-retry-duplicate", "response-model-mismatch", "response-model-opaque", "spawn-failure", "thinking-high", "thinking-drift", "duplicate-controller", "protected-compaction-cancel-before-gate", "protected-compaction-cancel-after-reserve", "protected-compaction-cancel-after-recheck", "protected-compaction-cancel-after-receiver", "protected-retry-cancel-before-gate", "protected-retry-cancel-after-reserve", "protected-retry-cancel-after-recheck", "protected-retry-cancel-after-receiver", "healthy", "broken-channel", "outside-scope", "wrong-thinking", "protected-budget", "protected-retry", "protected-retry-allowed", "protected-compaction-allowed", "proxy-unavailable", "telemetry-unavailable", "readonly-required", "protected-compaction", "protected-stream-error", "protected-truncated-stream", "protected-stream-complete", "protected-stream-timeout", "parent-helper", "telemetry-stale", "telemetry-account", "telemetry-bucket", "telemetry-source", "telemetry-fresh", "policy-change", "transport-cooldown", "transport-lease", "lost-observations", "cancel-preflight", "cancel-dispatch", "async-dispatch", "verify-stress", "cancel-find", "protected-race", "protected-cancel-before-gate", "protected-cancel-after-reserve", "protected-cancel-after-recheck", "protected-cancel-after-receiver"]) {
const ids: Record<string, string> = { "writers-disabled": "CFG-004", "writers-disabled-child": "CFG-004", "protected-gate-unavailable": "RTB-007 T33", "protected-retry-duplicate": "RTB-013", "response-model-mismatch": "T17", "response-model-opaque": "T17", "spawn-failure": "EXE-005 T01", "thinking-high":"T04", "thinking-drift":"T04", "duplicate-controller": "EXE-009 T49", "protected-compaction-cancel-before-gate": "RTB-009", "protected-compaction-cancel-after-reserve": "RTB-009", "protected-compaction-cancel-after-recheck": "RTB-009", "protected-compaction-cancel-after-receiver": "RTB-011", "protected-retry-cancel-before-gate": "RTB-009", "protected-retry-cancel-after-reserve": "RTB-009", "protected-retry-cancel-after-recheck": "RTB-009", "protected-retry-cancel-after-receiver": "RTB-011", healthy: "EXE-007", "broken-channel": "EXE-003 T06", "outside-scope": "EXE-012", "wrong-thinking": "EXE-004 RTB-002", "protected-budget": "RTB-009", "protected-retry": "RTB-008 RTB-009", "protected-retry-allowed": "RTB-009", "protected-compaction-allowed": "RTB-008", "proxy-unavailable": "RTB-006", "telemetry-unavailable": "RTB-014", "readonly-required": "RTB-001 EXE-004", "protected-compaction": "RTB-008 T29 T67", "protected-stream-error": "REC-017", "protected-truncated-stream": "T23", "protected-stream-complete": "REC-018", "protected-stream-timeout": "REC-012", "parent-helper": "T67", "telemetry-stale": "RTB-014", "telemetry-account": "RTB-014", "telemetry-bucket": "RTB-014", "telemetry-source": "RTB-014", "telemetry-fresh": "RTB-014", "policy-change": "CFG-007", "transport-cooldown": "", "transport-lease": "", "lost-observations": "EXE-012 T52 T07", "cancel-preflight": "EXE-011", "cancel-dispatch": "EXE-011", "async-dispatch": "EXE-008", "verify-stress": "", "cancel-find": "EXE-011 T41", "protected-race": "RTB-009", "protected-cancel-before-gate": "RTB-009", "protected-cancel-after-reserve": "RTB-009", "protected-cancel-after-recheck": "RTB-009", "protected-cancel-after-receiver": "RTB-011" };
test(`[A/P ${ids[variant]}] public pi-subagents ${variant} preserves guarded execution and failure evidence`, { timeout: 45000 }, async (t) => {
  const root = isolatedDirectory(t), agentDir = join(root, "agent"), cwd = join(root, "workspace");
  mkdirSync(agentDir, { mode: 0o700 }); mkdirSync(cwd, { mode: 0o700 });
  const sourcePkg = fileURLToPath(new URL("..", import.meta.url));
  const retryCancellation = variant.startsWith("protected-retry-cancel-"), compactionCancellation = variant.startsWith("protected-compaction-cancel-"), auxiliaryCancellation = retryCancellation || compactionCancellation;
  const gateCut = variant.includes("-cancel-") ? childGateCut(sourcePkg, root, variant.split("-cancel-")[1], compactionCancellation ? 3 : retryCancellation ? 2 : 1, compactionCancellation) : null;
  if (gateCut) t.after(() => gateCut.close());
  const pkg = gateCut?.copy ?? (variant === "writers-disabled-child" ? writerParentCut(sourcePkg, root) : variant === "protected-retry-duplicate" ? settlementReplay(sourcePkg,root) : variant === "thinking-drift" ? thinkingCut(sourcePkg,root) : sourcePkg), subagents = join(pkg, "node_modules/pi-subagents/index.ts");
  let requests = 0; const domainClaimsAtSend: number[] = [], requestBodies: string[] = [], responseBodies: string[] = [];
  const server = createServer((req, res) => {
    if (variant.startsWith("response-model-")) {
      const write=res.write.bind(res); let sent="";
      res.write=((chunk: any,...args: any[])=>{sent+=String(chunk);return (write as any)(chunk,...args);}) as typeof res.write;
      res.on("finish",()=>responseBodies.push(sent));
    }
    let body = ""; req.on("data", chunk => { body += chunk; }); req.on("end", () => {
      requests++; requestBodies.push(body);
      if (variant.startsWith("transport-")) {
        const observer = new Store(dirname(config.storage.path));
        if (requests === 1) observer.put("transport-incidents", config.routes.primary.transportDomain, { id: "external-network-incident", status: "OPEN", failures: 1,
          notBefore: variant === "transport-cooldown" ? Date.now() + 60000 : 0, domain: { kind: "transport", id: config.routes.primary.transportDomain } });
        domainClaimsAtSend.push(observer.claims().filter(claim => String(claim.resource_id).startsWith("transport-")).length); observer.close();
      }
      if (requests === 1 && variant.startsWith("telemetry-") && variant !== "telemetry-unavailable") {
        const observation = { account: config.routes.primary.accountBinding, bucket: config.routes.primary.quotaGroup, source: "fixture", observedAt: Date.now(), remaining: 10, resetAt: null };
        if (variant === "telemetry-stale") observation.observedAt = 0;
        if (variant === "telemetry-account") observation.account = "another-account";
        if (variant === "telemetry-bucket") observation.bucket = "another-bucket";
        if (variant === "telemetry-source") observation.source = "another-source";
        writeFileSync(join(root, "observation.json"), JSON.stringify(observation), { mode: 0o600 });
      }
      if (requests === 1 && variant === "policy-change") {
        const changed = structuredClone(config); changed.budget.protectedAttemptsPerWorkScope = 1;
        writeFileSync(configPath, JSON.stringify(changed));
      }
      if (variant.startsWith("response-model-")) { answer(res, requests === 1, false, 10, false, variant === "response-model-mismatch" ? "different-response-model" : null); return; }
      if (variant === "protected-race" || variant === "protected-gate-unavailable") { answer(res, false, false); return; }
      if (variant === "protected-stream-complete") { answer(res, false, false); return; }
      if (variant === "protected-stream-timeout") { res.writeHead(200, { "content-type": "text/event-stream" }); res.flushHeaders(); res.write('data: {"choices":[{"index":0,"delta":{"content":"unfinished"},"finish_reason":null}]}\n\n'); return; }
      if (variant === "protected-stream-error" || variant === "protected-truncated-stream") {
        res.writeHead(200, { "content-type": "text/event-stream" });
        const event = variant === "protected-stream-error" ? { error: { code: "fixture_error", message: "synthetic stream failure" } }
          : { id: "fixture", model: "fixture-model", choices: [{ index: 0, delta: { role: "assistant", content: "incomplete" }, finish_reason: null }] };
        res.end(`data: ${JSON.stringify(event)}\n\n`); return;
      }
      if (variant.startsWith("protected-retry") && requests === 1) {
        res.writeHead(429, { "content-type": "application/json", "retry-after": "0" });
        res.end(JSON.stringify({ error: { message: "fixture limit", code: "rate_limit" } })); return;
      }
      answer(res, requests === 1 && variant !== "parent-helper", (variant === "outside-scope" || variant === "lost-observations"), variant.startsWith("protected-compaction") ? 31000 : 10, variant === "cancel-find");
    });
  });
  await listenLoopback(server);
  const port = (server.address() as { port: number }).port;
  writeFileSync(join(agentDir, "models.json"), JSON.stringify({ providers: { "fixture-provider": { baseUrl: `http://127.0.0.1:${port}/v1`,
    apiKey: "fixture-key-not-real", api: "openai-completions", models: [{ id: "fixture-model", name: "Fixture", reasoning: variant.startsWith("thinking-"),
      input: ["text"], contextWindow: 32000, maxTokens: 1000, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } }));
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [pkg], compaction: { enabled: variant.startsWith("protected-compaction"), reserveTokens: 1024, keepRecentTokens: 1 },
    retry: { enabled: false, provider: { maxRetries: variant.startsWith("protected-retry") ? 2 : 0 } }, enableInstallTelemetry: false, quietStartup: true }));
  const config = configured(); config.recovery.requestTimeoutMs=25000;config.storage.path = join(root, "state/runtime.db");
  config.features.interactiveRecovery = false; config.features.managedWorkflows = true;
  config.executionProfiles.worker = { tools: ["read", "grep", "find", "ls", "write", "edit"], requiredCapabilities: [], timeoutMs: 25000,
    maxModelTurns: 10, toolTimeoutMs: 10000, thinking: "off" };
  config.roles.worker = { route: "primary", profileRef: "worker" };
  if (variant.startsWith("writers-disabled")) config.limits.writersPerJob = 0;
  if (variant === "proxy-unavailable") config.network.local = { type: "socks5h", endpoint: "socks5h://127.0.0.1:1" };
  if (variant === "telemetry-unavailable") {
    config.routes.primary.telemetry = "quota";
    config.telemetryBindings.quota = { path: join(root, "missing-observation.json"), accountBinding: config.routes.primary.accountBinding,
      bucket: config.routes.primary.quotaGroup, source: "fixture", freshnessMs: 1000, minimumRemaining: 1 };
  }
  if ((variant.startsWith("telemetry-") && variant !== "telemetry-unavailable") || variant === "policy-change" || variant.startsWith("transport-")) {
    config.routes.primary.protected = true;
    config.routes.primary.telemetry = "quota";
    config.telemetryBindings.quota = { path: join(root, "observation.json"), accountBinding: config.routes.primary.accountBinding,
      bucket: config.routes.primary.quotaGroup, source: "fixture", freshnessMs: 60000, minimumRemaining: 1 };
    writeFileSync(join(root, "observation.json"), JSON.stringify({ account: config.routes.primary.accountBinding,
      bucket: config.routes.primary.quotaGroup, source: "fixture", observedAt: Date.now(), remaining: 10, resetAt: null }), { mode: 0o600 });
  }
  if (variant === "readonly-required") config.executionProfiles.worker.requiredCapabilities = ["readonly"];
  if (variant === "wrong-thinking" || variant.startsWith("thinking-")) config.executionProfiles.worker.thinking = "high";
  if (variant.startsWith("protected-")) { config.routes.primary.protected = true; config.budget.protectedAttemptsPerWorkScope = compactionCancellation ? 4 : retryCancellation ? 2 : variant === "protected-compaction-allowed" ? 4 : ["protected-retry-duplicate", "protected-compaction", "protected-retry-allowed"].includes(variant) ? 2 : 1; }
  if(variant === "protected-stream-timeout")config.recovery.policies.providers["fixture-provider"]={requestTimeout:"1s"};
  const configPath = join(root, "task-keeper.json"); writeFileSync(configPath, JSON.stringify(config));
  const shimDir = join(root, "shim"); mkdirSync(shimDir);
  if (variant === "cancel-find") writeFileSync(join(shimDir, "fd"), `#!${process.execPath}
const fs=require('node:fs'); if(process.argv.includes('--version')) process.exit(0);
process.on('SIGTERM',()=>{}); fs.writeFileSync(${JSON.stringify(join(cwd, "find-ready.json.tmp"))},JSON.stringify({pid:process.pid}));fs.renameSync(${JSON.stringify(join(cwd, "find-ready.json.tmp"))},${JSON.stringify(join(cwd, "find-ready.json"))});
setInterval(()=>{},1000);
`, { mode: 0o700 });
  let credentialBarrierReached = false;
  if (variant === "protected-race") {
    const release = join(cwd, "release-credentials"), helper = join(root, "credentials.cjs");
    writeFileSync(helper, `const fs=require('node:fs');const path=require('node:path');
if(process.cwd()===${JSON.stringify(cwd)}){console.log('fixture-key');process.exit(0);}
fs.writeFileSync(path.join(process.cwd(),'credential-ready.tmp'),JSON.stringify({pid:process.pid,cwd:process.cwd()}));fs.renameSync(path.join(process.cwd(),'credential-ready.tmp'),path.join(process.cwd(),'credential-ready.json'));
const started=Date.now();const timer=setInterval(()=>{if(fs.existsSync(${JSON.stringify(release)})){clearInterval(timer);console.log('fixture-key');}else if(Date.now()-started>12000){clearInterval(timer);process.exit(1);}},5);
`);
    const modelsPath = join(agentDir, "models.json"), models = JSON.parse(readFileSync(modelsPath, "utf8"));
    models.providers["fixture-provider"].apiKey = `!${process.execPath} ${helper}`; writeFileSync(modelsPath, JSON.stringify(models));
    const watcher = watch(cwd, { recursive: true }, () => {
      if (!credentialBarrierReached && ["a", "b"].every(label => existsSync(join(cwd, `child-${label}/credential-ready.json`)))) {
        credentialBarrierReached = true; writeFileSync(release, "release both prepared native processes");
      }
    }); t.after(() => watcher.close());
  }
  const cli = join(pkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js");
  const harness = join(pkg, "tests/fixtures/subagents-harness.ts");
  const child = spawn(process.execPath, [cli, "--mode", "rpc", "--no-extensions", "-e", subagents, ...(variant === "spawn-failure" ? ["-e", join(pkg, "tests/fixtures/native-spawn-error.ts")] : []), "-e", harness, "--no-skills",
    "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline", "--provider", "fixture-provider", "--model", "fixture-model", "--thinking", "off",
    "--no-tools", "--session-dir", join(root, "sessions")], { cwd, stdio: ["pipe", "pipe", "pipe"], env: {
      PATH: `${shimDir}:${join(pkg, "node_modules/.bin")}:${process.env.PATH}`, LANG: "C.UTF-8", PI_CODING_AGENT_DIR: agentDir,
      PI_TASK_KEEPER_CONFIG: configPath, PI_SUBAGENTS_TEMP_ROOT: join(root, "native-subagents"), PI_MODEL_EXCLUSIONS_PATH: join(root, "native-exclusions.json"), PI_OFFLINE: "1", PI_TELEMETRY: "0",
    } });
  let output = "", errors = "";
  child.stdout.on("data", (data) => { output = (output + data).slice(-24000); });
  child.stderr.on("data", (data) => { errors = (errors + data).slice(-12000); });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGTERM"); await exit; }
    server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve()));
  });
  child.stdin.write(JSON.stringify({ type: "prompt", message: `/tk-delegate ${(["protected-gate-unavailable", "duplicate-controller", "broken-channel", "lost-observations", "cancel-preflight", "cancel-dispatch", "async-dispatch", "verify-stress", "cancel-find", "protected-race"].includes(variant)) ? variant : variant === "protected-race" ? "race-work-budget" : variant.startsWith("protected-compaction") ? "compaction" : variant === "parent-helper" ? "parent-helper" : "worker"}`, id: "delegate" }) + "\n");
  const resultPath = join(dirname(config.storage.path), "adapter-result.json"), deadline = Date.now() + 35000;
  while (!existsSync(resultPath)) {
    if (Date.now() > deadline || child.exitCode !== null) throw new Error(`No result; requests=${requests}; out=${output}; err=${errors}`);
    await delay(20);
  }
  const result = JSON.parse(readFileSync(resultPath, "utf8"));
  const observe=(ac:string,name:string,check:()=>void)=>acceptance(ac,name,{level:"A",observer:"actual-pi-subagents-native-result-and-loopback-receiver",predicate:name,artifact:observerArtifact(`${variant}-${name}`,{result,requests,requestBodies})},check);
  if(variant === "thinking-drift")observe("AC25","profile-drift",()=>{assert.equal(requests,0);assert.match(result.error,/CHILD_MODEL_CONTRACT_MISMATCH/);assert.notEqual(result.status,"ended");});
  if(variant === "duplicate-controller")observe("AC25","unsupported-mode",()=>{assert.equal(requests,0);assert.equal(result.error,"ACTIVE_SUBAGENTS_RUNTIME_NOT_CERTIFIED");assert.equal(result.nativeRunId??null,null);});
  if(variant === "broken-channel")observe("AC25","reporter-failure",()=>{assert.equal(requests,0);assert.notEqual(result.status,"ended");assert.ok(result.error);assert.equal(result.observations.length,0);});
  if(variant === "spawn-failure")observe("AC25","accepted-not-started",()=>{assert.equal(requests,0);assert.ok(result.nativeRunId);assert.equal(result.nativeStatus,"failed");assert.equal(result.terminationConfirmed,false);assert.match(result.error,/ENOENT/);});
  if(["protected-budget","protected-retry-allowed","protected-compaction-allowed"].includes(variant))observe("AC29",variant === "protected-budget"?"child-main":variant === "protected-retry-allowed"?"child-retry":"child-compaction",()=>{
    const ledger=new Store(dirname(config.storage.path));try{assert.ok(requests>0);assert.equal(Number(ledger.bucket("work-harness-parent")!.used),requests);assert.equal(ledger.bucket("work-harness-parent")!.reserved,0);if(variant === "protected-budget")assert.ok(result.observations.some((o:any)=>o.requestDenials.includes("BUDGET_DENIED")));else assert.equal(result.status,"ended");}finally{ledger.close();}
  });
  if(variant === "parent-helper")observe("AC29","parent-helper-denied",()=>{assert.equal(result.blocked,true);assert.ok(result.denied>0);assert.equal(result.ordinary,"stop");assert.equal(requests,1);});
  if(variant === "protected-gate-unavailable")observe("AC29","parent-protected-denied",()=>{assert.equal(result.completed,false);assert.equal(result.reason,"PARENT_HELPER_GATE_CHANGED");assert.deepEqual(result.requests,[]);assert.deepEqual(result.grants,[]);});
  if(variant === "proxy-unavailable")observe("AC29","unsupported-network",()=>{assert.equal(requests,0);assert.notEqual(result.status,"ended");assert.ok(result.error);});
  if(["telemetry-stale","telemetry-account","telemetry-bucket","telemetry-source"].includes(variant))observe("AC29","wrong-telemetry",()=>{assert.equal(requests,1);assert.notEqual(result.status,"ended");assert.ok(result.observations.some((o:any)=>o.requestDenials.includes("QUOTA_TELEMETRY_NOT_ELIGIBLE")));});

  if (variant.startsWith("writers-disabled")) {
    const observer = new Store(dirname(config.storage.path)); t.after(() => observer.close());
    assert.match(result.error, /WRITERS_DISABLED/); assert.equal(requests, 0); assert.equal(existsSync(join(cwd, "candidate.txt")), false);
    assert.deepEqual(observer.list("child-observations"), []); assert.deepEqual(observer.claims(), []);
    const grants = observer.list<{active: boolean}>("child-grants");
    assert.equal(grants.length, variant === "writers-disabled-child" ? 1 : 0); assert.ok(grants.every(row => !row.value.active));
    if (variant === "writers-disabled-child") { assert.ok(result.nativeRunId); assert.notEqual(result.status, "ended"); assert.equal(result.terminationConfirmed, true); }
    else assert.equal(result.nativeRunId ?? null, null);
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "writer-observers"); mkdirSync(path, { recursive: true });
      writeFileSync(join(path, `${variant}.json`), JSON.stringify({ result, requests, grants, claims: observer.claims(),
        fault: variant === "writers-disabled-child" ? JSON.parse(readFileSync(join(root, "writer-fault-manifest.json"), "utf8")) : null }, null, 2)); }
    return;
  }
  if(variant === "protected-gate-unavailable"){
    for(const id of ["RTB-007","T33"])evidence(id,()=>{
      assert.equal(config.routes.primary.protected,true);assert.equal(result.gateHealthy,false);assert.equal(result.completed,false);
      assert.equal(result.reason,"PARENT_HELPER_GATE_CHANGED");assert.deepEqual(result.grants,[]);assert.deepEqual(result.observations,[]);
      assert.deepEqual(result.requests,[]);assert.deepEqual(result.claims,[]);assert.equal(requests,1);assert.equal(result.ordinary,"stop");
      assert.ok(requestBodies[0].includes("Independent unprotected availability witness"));assert.equal(existsSync(join(cwd,"candidate.txt")),false);
    });
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"gate-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"unavailable.json"),JSON.stringify({result,requestBodies,requests},null,2));}
    return;
  }

  if(variant === "protected-retry-duplicate"){
    const observer=new Store(dirname(config.storage.path));t.after(()=>observer.close());
    const rows=observer.db.prepare("SELECT * FROM requests ORDER BY rowid").all(),events=observer.events("harness-parent");
    const replay=readFileSync(join(root,"settlement-observer.jsonl"),"utf8").trim().split("\n").map(line=>JSON.parse(line));
    assert.equal(requests,2);assert.equal(result.status,"ended");assert.equal(result.terminationConfirmed,true);
    assert.equal(rows.length,2);assert.notEqual(rows[0].id,rows[1].id);assert.ok(rows.every(row=>row.state==="sent"));
    assert.equal(requestBodies[0],requestBodies[1]);assert.equal(result.observations[0].sequence>0,true);
    const attempts=events.filter(event=>event.kind==="http_attempt"),responses=events.filter(event=>event.kind==="http_response");
    assert.equal(attempts.length,2);assert.equal(responses.length,2);assert.deepEqual(responses.map(event=>event.payload.status),[429,200]);
    assert.deepEqual(attempts.map(event=>event.payload.requestId),rows.map(row=>row.id));
    assert.equal(replay.length,4);assert.deepEqual(replay.map(row=>row.phase),["unknown-duplicate","sent-duplicate","unknown-duplicate","sent-duplicate"]);
    for(const row of replay){assert.deepEqual(row.after,row.before);assert.ok(rows.some(request=>request.id===row.requestId));}
    for(const name of ["duplicate-settlement","unknown-charge"])observe("AC29",name,()=>{assert.equal(requests,2);assert.equal(rows.length,2);assert.equal(replay.length,4);for(const row of replay)assert.deepEqual(row.before,row.after);assert.ok(replay.some(row=>row.phase==="unknown-duplicate"&&row.before.some((bucket:any)=>bucket.reserved===1)));});
    const work=observer.bucket("work-harness-parent")!;assert.equal(work.used,2);assert.equal(work.reserved,0);assert.equal(work.ceiling,2);
    assert.equal(replay[0].before.find((row:{id:string})=>row.id==="work-harness-parent").reserved,1);
    assert.equal(replay[2].before.find((row:{id:string})=>row.id==="work-harness-parent").used,1);
    assert.equal(replay[2].before.find((row:{id:string})=>row.id==="work-harness-parent").reserved,1);
    assert.equal(observer.claims().length,0);assert.equal(existsSync(join(cwd,"candidate.txt")),false);
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"settlement-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"native-retry-duplicates.json"),JSON.stringify({rows,events,replay,result,requestBodies,work,manifest:JSON.parse(readFileSync(join(root,"settlement-fault-manifest.json"),"utf8"))},null,2));}
    return;
  }

  if (variant.startsWith("response-model-")) {
    const observer=new Store(dirname(config.storage.path));t.after(()=>observer.close());
    const descriptor=JSON.parse(readFileSync(join(observer.root,"child-contexts",`${result.descriptorId}.json`),"utf8"));
    assert.equal(requests,2);assert.ok(requestBodies.every(body=>JSON.parse(body).model==="fixture-model"));
    assert.equal(responseBodies.length,2);
    const frames=responseBodies.flatMap(body=>body.split("\n").filter(line=>line.startsWith("data: {")).map(line=>JSON.parse(line.slice(6))));
    assert.equal(frames.length,4);
    if(variant==="response-model-mismatch")assert.ok(frames.every(frame=>frame.model==="different-response-model"));
    else assert.ok(frames.every(frame=>!("model" in frame)));

    assert.equal(descriptor.model,"fixture-model");assert.equal(result.status,"ended");assert.equal(result.terminationConfirmed,true);
    assert.equal(result.observations.length,1);assert.equal(result.observations[0].model,"fixture-model");assert.equal(result.observations[0].settled,true);
    assert.deepEqual(result.modelIdentity,{requested:{provider:"fixture-provider",model:"fixture-model"},runtimeObservationSource:"client_configuration",responseModel:null,serverWeights:"unverified"});
    assert.equal(result.modelIdentity.responseModel,null);assert.equal(readFileSync(join(cwd,"candidate.txt"),"utf8"),"guarded\n");
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"model-identity-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,`${variant}.json`),JSON.stringify({responseBodies,requestBodies,descriptor,result},null,2));}
    return;
  }
  if (variant === "spawn-failure") {
    const observer = new Store(dirname(config.storage.path)); t.after(() => observer.close());
    const witness = JSON.parse(readFileSync(join(observer.root, "native-spawn-error.json"), "utf8"));
    for (const id of ["EXE-005", "T01"]) evidence(id, () => {
      assert.equal(witness.attempts.length, 1); assert.equal(witness.attempts[0].spawned, false); assert.equal(witness.attempts[0].pid, null);
      assert.equal(witness.attempts[0].error.code, "ENOENT"); assert.match(witness.attempts[0].error.syscall, /^spawn /);
      assert.equal(witness.responses.length, 1); const native = witness.responses[0].response;
      assert.equal(native.status, "failed"); assert.equal(native.exitCode, 1); assert.ok(native.runId);
      assert.equal(native.requestId, result.descriptorId); assert.equal(result.nativeRunId, native.runId);
      assert.equal(result.nativeStatus, "failed"); assert.equal(result.nativeExitCode, 1); assert.match(result.error, /ENOENT/);
      assert.notEqual(result.status, "ended"); assert.equal(result.terminationConfirmed, false);
      assert.equal(result.notSent, false); // Delegation reached the backend; HTTP sending is a separate fact.
      assert.equal(requests, 0); assert.equal(observer.list("child-observations").length, 0);
      assert.equal(observer.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0);
      assert.equal(existsSync(join(cwd, "candidate.txt")), false);
    });
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"native-start-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"adapter-spawn-failure.json"),JSON.stringify({witness,result,requests,claims:observer.claims()},null,2)); }
    return;
  }
  if (gateCut) {
    const cut = variant.split("-cancel-")[1], observer = new Store(dirname(config.storage.path)); t.after(() => observer.close());
    const invocationPath = join(root, "gate-invocations.jsonl");
    const invocations: Array<{requestId: string; databaseTransaction: boolean}> = existsSync(invocationPath)
      ? readFileSync(invocationPath, "utf8").trim().split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
    const records = process.env.TASK_KEEPER_TEST_RECORD_DIR;
    if (records) {
      const artifactRoot = join(dirname(records), "gate-observers"); mkdirSync(artifactRoot, { recursive: true });
      writeFileSync(join(artifactRoot, `${variant}.json`), JSON.stringify({ variant, reached: gateCut.observed(), invocations,
        faultManifest: JSON.parse(readFileSync(join(root, "gate-fault-manifest.json"), "utf8")), receiver: requestBodies.map(body => JSON.parse(body)),
        requests: observer.db.prepare("SELECT * FROM requests ORDER BY id").all(), budget: observer.bucket("work-harness-parent"),
        events: observer.events("harness-parent"), admissions: observer.list("request-admissions"), nativeResult: result }, null, 2));
    }
    observe("AC29","cancel-cuts",()=>{const prior=compactionCancellation?2:retryCancellation?1:0;assert.equal(gateCut.observed()?.cut,cut);assert.equal(requests,prior+Number(cut==="after-receiver"));assert.notEqual(result.status,"ended");assert.ok(invocations.every(item=>!item.databaseTransaction));});
    matrixCase("request-paths", `${retryCancellation ? "native-retry" : compactionCancellation ? "compaction" : "child"}.cancel-${cut}`, () => {
      assert.equal(gateCut.observed()?.cut, cut); assert.ok(gateCut.observed()?.pid);
      assert.ok(invocations.length >= requests); assert.ok(invocations.every(item => item.databaseTransaction === false));
      const priorRequests = compactionCancellation ? 2 : retryCancellation ? 1 : 0;
      assert.equal(gateCut.observed()?.call, priorRequests + 1);
      assert.equal(requests, priorRequests + (cut === "after-receiver" ? 1 : 0), JSON.stringify(result)); assert.notEqual(result.status, "ended");
      const rows = observer.db.prepare("SELECT state FROM requests").all();
      // SDK retries have no new before_provider_request hook. Cancellation at
      // the actual HTTP callback may reserve, then settle not_sent at the final signal check.
      const reservedAtCut = retryCancellation || cut !== "before-gate";
      assert.equal(rows.length, priorRequests + Number(reservedAtCut));
      assert.equal(rows.filter(row => row.state === "sent").length, priorRequests + (cut === "after-receiver" ? 1 : 0));
      assert.equal(rows.filter(row => row.state === "not_sent").length, reservedAtCut && cut !== "after-receiver" ? 1 : 0);
      assert.equal(Number(observer.bucket("work-harness-parent")?.used ?? 0), priorRequests + (cut === "after-receiver" ? 1 : 0));
      if (retryCancellation) {
        assert.equal(observer.db.prepare("SELECT count(*) n FROM events WHERE kind='model_input'").get()!.n, 1);
        if (requests === 2) assert.deepEqual(JSON.parse(requestBodies[1]).messages, JSON.parse(requestBodies[0]).messages);
      }
      assert.equal(Number(observer.bucket("work-harness-parent")?.reserved ?? 0), 0);
      if (compactionCancellation) {
        assert.ok(observer.db.prepare("SELECT count(*) n FROM events WHERE kind='compaction_start'").get()!.n);
        assert.equal(observer.db.prepare("SELECT count(*) n FROM events WHERE kind='model_input'").get()!.n, 2);
        assert.equal(readFileSync(join(cwd, "candidate.txt"), "utf8"), "guarded\n");
      } else assert.equal(existsSync(join(cwd, "candidate.txt")), false);
    }); return;
  }
  if (variant === "protected-race") {
    const observer = new Store(dirname(config.storage.path)); t.after(() => observer.close());
    assert.equal(credentialBarrierReached, true); assert.equal(requests, 1, JSON.stringify(result));
    assert.equal(result.results.length, 2); assert.equal(result.results.filter((item: {status: string}) => item.status === "ended").length, 1);
    const winner = result.results.findIndex((item: {status: string}) => item.status === "ended"), loser = result.results[1 - winner];
    assert.ok(requestBodies[0].includes(`Budget race child ${winner === 0 ? "a" : "b"}`));
    assert.ok(loser.observations.some((item: {requestDenials:string[]}) => item.requestDenials.includes("BUDGET_DENIED")));
    const observed = result.results.flatMap((item: {observations: unknown[]}) => item.observations);
    assert.equal(new Set(observed.map((item: {process: {pid: number}}) => item.process.pid)).size, 2);
    assert.equal(observer.bucket("work-harness-parent")!.used, 1); assert.equal(observer.bucket("work-harness-parent")!.reserved, 0);
    assert.equal(observer.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1);
    assert.equal(observer.claims().length, 0);
    observe("AC29","last-permit",()=>{assert.equal(requests,1);assert.equal(observer.bucket("work-harness-parent")!.used,1);assert.equal(observer.bucket("work-harness-parent")!.reserved,0);assert.equal(new Set(observed.map((item:any)=>item.process.pid)).size,2);assert.ok(loser.observations.some((o:any)=>o.requestDenials.includes("BUDGET_DENIED")));});
    matrixCase("request-paths", "child.allowed", () => {
      assert.equal(result.results[winner].status, "ended"); assert.equal(requests, 1); assert.equal(observer.bucket("work-harness-parent")!.used, 1);
      assert.ok(requestBodies[0].includes(`Budget race child ${winner === 0 ? "a" : "b"}`));
    });
    matrixCase("request-paths", "child.denied", () => {
      assert.notEqual(loser.status, "ended"); assert.equal(requestBodies.some(body => body.includes(`Budget race child ${winner === 0 ? "b" : "a"}`)), false);
      assert.ok(loser.observations.some((item: {requestDenials: string[]}) => item.requestDenials.includes("BUDGET_DENIED")));
    }); return;
  }
  if (variant === "cancel-find") {
    const observer = new Store(dirname(config.storage.path)); t.after(() => observer.close());
    const marker = JSON.parse(readFileSync(join(cwd, "find-ready.json"), "utf8"));
    const identity = processIdentity(marker.pid); assert.ok(identity);
    t.after(() => { if (originalProcessStopped(identity) === false) process.kill(identity.pid, "SIGKILL"); });
    for (const id of ["EXE-011", "T41"]) evidence(id, () => {
      assert.equal(requests, 1); assert.equal(result.status, "unknown"); assert.equal(result.terminationConfirmed, false);
      assert.equal(originalProcessStopped(identity), false); assert.ok(observer.claims().length > 0);
      assert.ok(result.observations.some((item: {externalWork?: string[]}) => item.externalWork?.length));
      assert.equal(existsSync(join(cwd, "candidate.txt")), false);
    });
    return;
  }
  if (variant === "verify-stress") {
    assert.equal(requests, 0); assert.equal(result.results.length, 100, JSON.stringify(result.results.at(-1)));
    assert.ok(result.results.every((item: { status: string }) => item.status === "passed")); return;
  }
  if (["cancel-preflight", "cancel-dispatch", "async-dispatch"].includes(variant)) {
    assert.equal(requests, 0); assert.equal(result.notSent, true); assert.equal(result.terminationConfirmed, true); assert.equal(result.status, "failed");
    assert.equal(result.nativeRunId, null); assert.equal(result.observations.length, 0);
    assert.equal(existsSync(join(dirname(config.storage.path), "unexpected-dispatch.json")), false);
    assert.equal(existsSync(join(cwd, "candidate.txt")), false);
    const observer = new Store(dirname(config.storage.path)); assert.equal(observer.claims().length, 0); observer.close(); return;
  }
  if (variant === "lost-observations") {
    const witness = JSON.parse(readFileSync(join(dirname(config.storage.path), "lost-observation-witness.json"), "utf8"));
    const observer = new Store(dirname(config.storage.path));
    for (const id of ["EXE-012", "T52", "T07"]) evidence(id, () => {
      assert.equal(witness.nativeStatus, "completed"); assert.equal(witness.exitCode, 0); assert.ok(witness.toolErrors.length > 0);
      assert.equal(witness.reporters.length, 1); assert.equal(witness.reporters[0].ready, true);
      assert.equal(observer.list("child-observations").length, 0); assert.equal(observer.db.prepare("SELECT count(*) n FROM events WHERE producer=?").get(witness.reporters[0].producerId)!.n, 0);
      assert.equal(result.status, "unknown"); assert.equal(result.terminationConfirmed, false); assert.equal(result.observations.length, 0);
      assert.ok(observer.claims().length > 0); assert.equal(existsSync(join(root, "escaped.txt")), false);
    });
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
      const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "preflight-observers"); mkdirSync(path,{recursive:true});
      writeFileSync(join(path,"lost-channel.json"),JSON.stringify({witness,result,requests,claims:observer.claims()},null,2));
    }
    observer.close(); return;
  }
  if (variant.startsWith("transport-")) {
    assert.equal(requests, variant === "transport-lease" ? 2 : 1); assert.equal(result.terminationConfirmed, true);
    assert.equal(result.status, variant === "transport-lease" ? "ended" : "failed", JSON.stringify(result));
    if (variant === "transport-cooldown") assert.ok(result.observations.some((o: {requestDenials: string[]}) => o.requestDenials.includes("SHARED_ROUTE_NOT_BEFORE")));
    else assert.deepEqual(domainClaimsAtSend, [0, 1]);
    const observer = new Store(dirname(config.storage.path));
    assert.equal(observer.claims().filter(c => String(c.resource_id).startsWith("transport-")).length, 0); observer.close(); return;
  }
  if ((variant.startsWith("telemetry-") && variant !== "telemetry-unavailable") || variant === "policy-change") {
    const healthy = variant === "telemetry-fresh";
    assert.equal(requests, healthy ? 2 : 1, JSON.stringify(result));
    assert.equal(result.status, healthy ? "ended" : "failed", JSON.stringify(result));
    assert.equal(result.terminationConfirmed, true);
    const ledger = new Store(dirname(config.storage.path));
    const requestsInLedger = ledger.db.prepare("SELECT * FROM requests").all();
    assert.equal(requestsInLedger.length, healthy ? 2 : 1);
    assert.ok(requestsInLedger.every(row => row.state === "sent"));
    ledger.close();
    if (!healthy) assert.ok(result.observations.some((o: { requestDenials: string[]; toolErrors: Array<{ error: string }> }) =>
      variant === "policy-change" ? o.toolErrors.some(error => error.error.includes("CHILD_POLICY_CHANGED")) || o.requestDenials.includes("CHILD_POLICY_CHANGED")
        : o.requestDenials.includes("QUOTA_TELEMETRY_NOT_ELIGIBLE")), JSON.stringify(result));
    return;
  }
  if (variant === "parent-helper") {
    assert.equal(result.blocked, true); assert.ok(result.denied > 0); assert.equal(result.ordinary, "stop"); assert.equal(requests, 1);
    const ledger = new Store(dirname(config.storage.path));
    assert.equal(ledger.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0); ledger.close(); return;
  }
  if (["protected-stream-error", "protected-truncated-stream", "protected-stream-complete", "protected-stream-timeout"].includes(variant)) {
    const terminal = variant === "protected-stream-complete" ? "complete" : variant === "protected-stream-error" ? "error" : variant === "protected-truncated-stream" ? "truncated" : "timeout";
    const ledger = new Store(dirname(config.storage.path)); t.after(() => ledger.close());
    matrixCase("stream-terminals", terminal, () => {
      assert.equal(requests, 1); assert.equal(result.status === "ended", terminal === "complete", JSON.stringify(result));
      assert.equal(ledger.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1);
      const request = ledger.db.prepare("SELECT state FROM requests").get()!; assert.equal(request.state, "sent");
      assert.equal(result.observations.length, 1); assert.equal(result.observations[0].lastResponse?.status, 200);
      assert.equal(existsSync(join(cwd, "candidate.txt")), false);
      if(terminal === "timeout")assert.ok(ledger.events("harness-parent").some(event=>event.kind==="request_timeout"));
      if (terminal === "complete") {
        assert.equal(result.observations[0].stopReason, "stop"); assert.equal(result.terminationConfirmed, true);
      } else {
        assert.notEqual(result.observations[0].stopReason, "stop");
        assert.ok(result.error || result.observations[0].lastError || result.observations[0].stopReason === "aborted");
      }
    });
    return;
  }
  if (["protected-retry-allowed", "protected-compaction-allowed"].includes(variant)) {
    const ledger = new Store(dirname(config.storage.path)); t.after(() => ledger.close());
    matrixCase("request-paths", variant === "protected-retry-allowed" ? "native-retry.allowed" : "compaction.allowed", () => {
      assert.equal(result.status, "ended", JSON.stringify(result)); assert.equal(result.terminationConfirmed, true);
      assert.equal(ledger.db.prepare("SELECT count(*) n FROM requests WHERE state='sent'").get()!.n, requests);
      assert.equal(ledger.bucket("work-harness-parent")!.used, requests); assert.equal(ledger.bucket("work-harness-parent")!.reserved, 0);
      assert.ok(result.observations.every((item: {requestDenials: string[]}) => item.requestDenials.length === 0));
      if (variant === "protected-retry-allowed") assert.equal(requests, 2);
      else {
        assert.ok(requests >= 3 && requests <= 4);
        assert.ok(result.observations.some((item: {contextOperations?: Array<{status: string}>}) => item.contextOperations?.some(operation => operation.status === "completed")));
        assert.equal(readFileSync(join(cwd, "candidate.txt"), "utf8"), "guarded\n");
      }
    }); return;
  }
  if (variant.startsWith("protected-")) {
    if (variant !== "protected-compaction") assert.notEqual(result.status, "ended", JSON.stringify(result));
    assert.equal(requests, variant === "protected-compaction" ? 2 : 1);
    if (variant === "protected-compaction") for (const id of ["RTB-008", "T29", "T67"]) evidence(id, () => {
      assert.ok(result.observations.some((observation: { contextOperations?: Array<{ reason: string; status: string }> }) => observation.contextOperations?.some(operation => operation.reason === "threshold" && operation.status === "failed")), JSON.stringify(result));
      assert.equal(requests, 2); assert.equal(result.terminationConfirmed, true);
    });
    assert.ok(result.observations.some((observation: { requestGate: boolean; requestDenials: string[] }) => observation.requestGate && observation.requestDenials.includes("BUDGET_DENIED")), JSON.stringify(result));
    if (variant === "protected-retry" || variant === "protected-compaction") matrixCase("request-paths", variant === "protected-retry" ? "native-retry.denied" : "compaction.denied", () => {
      const ledger = new Store(dirname(config.storage.path));
      try {
        assert.equal(requests, variant === "protected-retry" ? 1 : 2); assert.equal(ledger.bucket("work-harness-parent")!.used, requests);
        assert.equal(ledger.bucket("work-harness-parent")!.reserved, 0);
        assert.ok(result.observations.some((item: {requestDenials:string[]}) => item.requestDenials.includes("BUDGET_DENIED")));
      } finally { ledger.close(); }
    });
    return;
  }
  if(variant === "thinking-drift"){
    const witness=JSON.parse(readFileSync(join(dirname(config.storage.path),"thinking-cut.json"),"utf8"));
    assert.equal(witness.requested,"high");assert.equal(witness.before,"high");assert.equal(witness.actual,"off");assert.equal(witness.descriptorId,result.descriptorId);
    assert.notEqual(result.status,"ended");assert.equal(requests,0);assert.match(result.error,/CHILD_MODEL_CONTRACT_MISMATCH/);assert.equal(existsSync(join(cwd,"candidate.txt")),false);
    assert.equal(JSON.parse(readFileSync(configPath,"utf8")).executionProfiles.worker.thinking,"high");
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"preflight-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"thinking-drift.json"),JSON.stringify({witness,result,requests},null,2));}return;
  }
  if (["duplicate-controller", "broken-channel", "wrong-thinking", "proxy-unavailable", "telemetry-unavailable", "readonly-required"].includes(variant)) {
    assert.notEqual(result.status, "ended", JSON.stringify(result)); assert.equal(requests, 0);
    assert.equal(existsSync(join(cwd, "candidate.txt")), false); assert.ok(result.error);
    if (variant === "broken-channel") {
      const witness=JSON.parse(readFileSync(join(dirname(config.storage.path),"broken-channel-witness.json"),"utf8"));
      const observer=new Store(dirname(config.storage.path));
      try {
        for(const id of ["EXE-003","T06"]) evidence(id,()=>{
          assert.equal(witness.status,"failed");assert.equal(witness.exitCode,1);assert.ok(witness.runId);assert.equal(witness.runId,result.nativeRunId);
          assert.equal(witness.requestId,result.descriptorId);assert.match(witness.error,/requested unavailable child tools/);
          for(const name of ["tk_read","tk_grep","tk_find","tk_ls","tk_write","tk_edit"])assert.ok(witness.error.includes(name));
          assert.equal(requests,0);assert.notEqual(result.status,"ended");assert.equal(observer.list("child-observations").length,0);
          assert.equal(existsSync(join(cwd,"candidate.txt")),false);
        });
        if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"preflight-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"required-tools-missing.json"),JSON.stringify({witness,result,requests,claims:observer.claims()},null,2));}
      }finally{observer.close();}
    }
    if (variant === "duplicate-controller") {
      const observer = new Store(dirname(config.storage.path));
      try { for (const id of ["EXE-009", "T49"]) evidence(id, () => {
        assert.equal(result.error, "ACTIVE_SUBAGENTS_RUNTIME_NOT_CERTIFIED"); assert.equal(requests, 0);
        assert.equal(result.nativeRunId ?? null, null); assert.equal(observer.list("child-observations").length, 0);
        assert.equal(observer.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0); assert.equal(observer.claims().length, 0);
        const probe = JSON.parse(readFileSync(join(observer.root, "duplicate-controller.json"), "utf8"));
        assert.equal(probe.extraOwnerReply, true); assert.equal(probe.replies.length, 2);
        assert.equal(probe.replies[0].id, probe.replies[1].id); assert.ok(probe.replies.every((reply: {version:string}) => reply.version === "task-keeper-recovery-owner-v2"));
        assert.equal(existsSync(join(cwd, "candidate.txt")), false);
      });
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "preflight-observers"); mkdirSync(path, {recursive:true});
        writeFileSync(join(path, "duplicate-controller.json"), JSON.stringify({result,requests,probe:JSON.parse(readFileSync(join(observer.root,"duplicate-controller.json"),"utf8")),claims:observer.claims()},null,2));
      }
      } finally { observer.close(); }
    }
    if (variant === "proxy-unavailable") {
      for (const id of ["RTB-006"]) evidence(id, () => {
        assert.notEqual(result.status, "ended"); assert.equal(requests, 0);
        assert.equal(existsSync(join(cwd, "candidate.txt")), false); assert.ok(result.error);
      });
    }
    if (variant === "wrong-thinking" || variant === "readonly-required") {
      const observer = new Store(dirname(config.storage.path));
      try { for (const id of ["EXE-004", variant === "wrong-thinking" ? "RTB-002" : "RTB-001"]) evidence(id, () => {
        assert.equal(requests, 0); assert.equal(result.nativeRunId ?? null, null); assert.equal(observer.list("child-observations").length, 0);
        assert.equal(result.error, variant === "wrong-thinking" ? "thinking_level_not_supported" : "CHILD_CAPABILITY_NOT_AVAILABLE");
        const actual = JSON.parse(readFileSync(configPath, "utf8")).executionProfiles.worker;
        if (variant === "wrong-thinking") assert.equal(actual.thinking, "high"); else assert.deepEqual(actual.requiredCapabilities, ["readonly"]);
        assert.equal(existsSync(join(cwd, "candidate.txt")), false);
      }); } finally { observer.close(); }
    }
    return;
  }
  assert.equal(result.status, "ended", JSON.stringify({ result, output, errors }));
  assert.ok(result.nativeRunId, "a completed execution needs a backend run identity");
  assert.equal(result.terminationConfirmed, true); assert.equal(result.observations.length, 1);
  assert.equal(result.observations[0].settled, true);
  if(variant === "thinking-high"){assert.equal(result.observations[0].thinking,"high");assert.equal(result.observations[0].ready,true);assert.equal(JSON.parse(readFileSync(configPath,"utf8")).executionProfiles.worker.thinking,"high");}
  if (variant === "outside-scope") {
    assert.equal(existsSync(join(root, "escaped.txt")), false);
    assert.equal(result.observations[0].toolErrors.length, 1);
  } else {
    assert.equal(result.observations[0].toolErrors.length, 0);
    assert.equal(readFileSync(join(cwd, "candidate.txt"), "utf8"), "guarded\n");
  }
  assert.equal(requests, 2);
});
}
