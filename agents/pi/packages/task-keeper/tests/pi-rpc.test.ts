import {nativeContinuationCut} from "./fixtures/native-continuation-cut.ts";
import { UsageLedger } from "../src/usage/ledger.ts";
import { continuationAckCut } from "./fixtures/continuation-ack-cut.ts";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { test, assert, evidence, matrixCase, acceptance, observerArtifact } from "./recorded-test.ts";
import { createServer, type ServerResponse } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, writeFileSync, readFileSync, cpSync, symlinkSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";
import { Store } from "../src/store/database.ts";
import type { RecoveryRecord } from "../src/reliability/recovery.ts";

function stream(res: ServerResponse, kind: "text" | "tool", inputTokens = 10, model = "fixture-model", cachedTokens = 0, includeUsage = true, outputTokens = 10, finishOverride?:string) {
  res.writeHead(200, { "content-type": "text/event-stream" });
  const delta = kind === "text" ? { role: "assistant", content: "Fixture task complete." }
    : { role: "assistant", tool_calls: [{ index: 0, id: "call-fixture-write", type: "function", function: { name: "write", arguments: JSON.stringify({ path: "proof.txt", content: "once\n" }) } }] };
  res.write(`data: ${JSON.stringify({ id: "chatcmpl-fixture", object: "chat.completion.chunk", created: 1, model, choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`);
  res.write(`data: ${JSON.stringify({ id: "chatcmpl-fixture", object: "chat.completion.chunk", created: 1, model, choices: [{ index: 0, delta: {}, finish_reason: finishOverride??(kind === "tool" ? "tool_calls" : "stop") }], ...(includeUsage?{usage: { prompt_tokens: inputTokens, prompt_tokens_details:{cached_tokens:cachedTokens}, completion_tokens: outputTokens, total_tokens: inputTokens + outputTokens }}:{}) })}\n\n`);
  res.end("data: [DONE]\n\n");
}

for (const variant of ["cut-continue-C0", "cut-continue-C1", "cut-continue-C2", "cut-continue-C3", "cut-continue-C4", "cut-continue-C5","toggle-usage", "explicit-zero", "metered-failure", "efficiency", "missing-usage", "sdk-aggregate-retry", "queued-tail", "usage-task", "cache-usage", "usage-only", "disabled", "auto-off-with-rules", "opinion-off", "current-session", "lost-ack","lifecycle-new", "lifecycle-switch", "lifecycle-fork", "lifecycle-shutdown","stream-error", "stream-truncated", "stream-timeout", "wait-deadline", "resume-cooldown", "request-timeout", "canary-timeout", "outer-recovery", "status-countdown", "native-retry", "write-before-limit", "restart-wait", "restart-overdue", "retry-after", "canary", "canary-false-positive", "without-subagents", "compaction-history", "native-retry-after", "service-a", "service-b", "observed-usage", "network-recovery", "service-hour-known", "service-hour-unknown", "service-auth", "service-context", "service-unknown", "with-subagents", "mixed-parent-profile", "pause-late-write", "auto-compaction", "auto-compaction-failure"] as const) {
  const ids: Record<string, string> = { "current-session": "", "lost-ack": "REC-021 T40", "lifecycle-new": "REC-020 T37", "lifecycle-switch": "REC-020 T37", "lifecycle-fork": "REC-020 T37", "lifecycle-shutdown": "REC-020 T37", "stream-error": "REC-017 T23", "stream-truncated": "REC-017 T23", "stream-timeout": "REC-012", "wait-deadline": "REC-011", "resume-cooldown": "CFG-013 REC-010", "request-timeout": "REC-012", "canary-timeout": "REC-012", "outer-recovery": "REC-018", "status-countdown": "CFG-014", "native-retry": "REC-006 T18", "write-before-limit": "REC-001 TK09", "restart-wait": "REC-009 TK11", "restart-overdue": "REC-009 TK11", "retry-after": "REC-008 REC-010", "canary": "REC-016", "canary-false-positive": "REC-015 REC-018 T22", "without-subagents": "CFG-010", "compaction-history": "EVD-004 VAL-015", "native-retry-after": "REC-006 REC-008 REC-010", "service-a": "CFG-002 REC-002 TK10", "service-b": "CFG-002 REC-002 TK10", "observed-usage": "REC-003 T20", "network-recovery": "REC-005", "service-hour-known": "REC-008 T21", "service-hour-unknown": "REC-008 T21", "service-auth": "REC-004 T26", "service-context": "REC-004 T26", "service-unknown": "REC-002", "with-subagents": "CFG-010", "mixed-parent-profile": "", "pause-late-write": "REC-019 T35", "auto-compaction": "REC-007 T19", "auto-compaction-failure": "REC-007 T19" };
  test(`[${variant.startsWith("cut-continue-")?"A P E":["retry-after", "canary", "canary-false-positive", "restart-wait", "restart-overdue", "wait-deadline", "lost-ack"].includes(variant) ? "A/P/E" : "A/E"} Q2 ${ids[variant]??""}] real Pi RPC ${variant} uses bounded native history and receiver-observed requests`, { timeout: 30000 }, async (t) => {
    const root = isolatedDirectory(t), agentDir = join(root, "agent"), cwd = join(root, "workspace");
    mkdirSync(agentDir, { mode: 0o700 }); mkdirSync(cwd, { mode: 0o700 });
    const service = variant === "service-a" || variant === "service-b";
    const providerId = service ? `binding-${variant}` : "fixture-provider", modelId = service ? `qwen-fixture-${variant}` : "fixture-model";
    const samples = JSON.parse(readFileSync(new URL("./fixtures/qwen-service-errors.json", import.meta.url), "utf8"));
    const errorCase: Record<string, string> = { "service-hour-known": "service-a-hour", "service-hour-unknown": "service-a-hour", "service-auth": "service-b-403", "service-context": "service-a-context", "service-unknown": "unknown-envelope" };
    const blockedService = ["service-hour-unknown", "service-auth", "service-context", "service-unknown", "mixed-parent-profile"].includes(variant);
    const sample = variant === "observed-usage" ? JSON.parse(readFileSync(new URL("./fixtures/qwen-observed-error.json", import.meta.url), "utf8"))
      : service || errorCase[variant] ? samples.cases.find((item: { id: string }) => item.id === (errorCase[variant] ?? `${variant}-resource`)) : null;
    const respond = (res: ServerResponse, kind: "text" | "tool", tokens = 10) => stream(res, kind, tokens, modelId, variant === "cache-usage"?6:0,variant!=="missing-usage");
    let heldWrite: ServerResponse | null = null;
    let timedOutConnectionClosed = false, streamHeadersSent = false;
    const requests: Array<Record<string, unknown>> = [];
    const requestTimes: number[] = [], requestWallTimes: number[] = [];
    const receiverStatuses: Array<{request: number; status: number}> = [];
    const canaryTransitions: Array<{ request: number; recovery: RecoveryRecord; incident: {id: string; status: string; failures: number} }> = [];
    const server = createServer((req, res) => {
      let input = "";
      req.on("data", (chunk) => { input += chunk; });
      req.on("end", () => {
        requests.push(JSON.parse(input));
        requestTimes.push(performance.now()); requestWallTimes.push(Date.now());
        const count = requests.length;
        if(variant === "cut-continue-C2" && count===2){writeFileSync(join(root,"continue-cut.json"),JSON.stringify({point:"C2",at:Date.now(),receiverCount:count}));return;}
        if(variant === "toggle-usage"){stream(res,"text");return;}
        if(variant === "explicit-zero"){stream(res,"text",0,String(requests[count-1].model),0,true,0);return;}
        if(variant === "metered-failure"){stream(res,"text",count===1?100:8,String(requests[count-1].model),0,true,count===1?50:2,count===1?"length":"stop");return;}
        if(variant === "efficiency"){stream(res,"text",count===1?8:4,String(requests[count-1].model),0,true,count===1?2:1);return;}
        if(variant === "queued-tail" && count===1){heldWrite=res;return;}
        if (variant === "lost-ack") {
          res.on("finish", () => receiverStatuses.push({request:count,status:res.statusCode}));
          if (count === 1 || count === 4) { res.writeHead(429,{"content-type":"application/json","retry-after":"1"});res.end('{"error":{"code":"rate_limit","message":"fixture quota"}}'); }
          else if (count === 2) heldWrite = res;
          else respond(res, "text");
          return;
        }
        res.on("finish", () => receiverStatuses.push({ request: count, status: res.statusCode }));
        if (variant === "canary-false-positive" && [3, 4, 5].includes(count)) {
          const observer = new Store(join(root, "state"));
          try { canaryTransitions.push({ request: count, recovery: observer.list<RecoveryRecord>("recovery")[0].value,
            incident: observer.get<{id: string; status: string; failures: number}>("incidents", "pool")! }); } finally { observer.close(); }
        }

        if ((variant === "stream-error" || variant === "stream-truncated") && count === 2) {
          res.writeHead(200,{"content-type":"text/event-stream","retry-after":"30"});streamHeadersSent=true;
          const event=variant === "stream-error" ? {error:{code:"fixture_stream_error",message:"STREAM_INNER_ERROR"}} : {id:"fixture",model:modelId,choices:[{index:0,delta:{role:"assistant",content:"STREAM_TRUNCATED_PARTIAL"},finish_reason:null}]};
          res.end(`data: ${JSON.stringify(event)}\n\n`);return;
        }
        if (variant.endsWith("-timeout") && count === 2) {
          if (variant === "stream-timeout") { res.writeHead(200,{"content-type":"text/event-stream"});res.flushHeaders();res.write('data: {"choices":[{"index":0,"delta":{"content":"STREAM_TIMEOUT_PARTIAL"},"finish_reason":null}]}\n\n');streamHeadersSent=true; }
          heldWrite = res; res.on("close", () => { timedOutConnectionClosed = true; }); return;
        }
        if (variant.startsWith("auto-compaction") && count === 2) { respond(res, "tool", 31000); return; }
        if (variant.startsWith("auto-compaction") && count === 3) { respond(res, "text", 31000); return; }
        if (variant === "auto-compaction-failure" && count === 4) {
          res.writeHead(429, { "content-type": "application/json", "retry-after": "0" }); res.end('{"error":{"message":"fixture summary limited","code":"rate_limit"}}'); return;
        }
        if (variant === "pause-late-write" && count === 2) { heldWrite = res; return; }
        if (variant === "pause-late-write" && count === 3) { respond(res, "tool"); return; }
        if (variant === "compaction-history" && count === 1) { respond(res, "text", 6000); return; }
        if ((variant === "write-before-limit" && count === 1) || (variant === "compaction-history" && count === 2)) { respond(res, "tool", variant === "compaction-history" ? 6000 : 10); return; }
        const limitedAt = ["usage-only","disabled","auto-off-with-rules","opinion-off"].includes(variant) ? Infinity : variant === "compaction-history" ? 3 : variant === "write-before-limit" ? 2 : 1;
        if (count === limitedAt || (variant === "canary-false-positive" && count === 3)) {
          res.writeHead(sample?.status ?? (variant === "network-recovery" ? 503 : 429), { "content-type": "application/json",
            ...(variant === "service-hour-unknown" ? {} : { "retry-after": ["resume-cooldown", "wait-deadline"].includes(variant) ? "5" : variant === "status-countdown" ? "30" : ["retry-after", "native-retry-after", "service-hour-known"].includes(variant) ? "1" : "0" }) });
          res.end(JSON.stringify(sample?.body ?? { error: { message: "fixture rate limit", type: "rate_limit_error", code: "rate_limit_exceeded" } }));
        } else respond(res, "text");
      });
    });
    await listenLoopback(server);
    const port = (server.address() as { port: number }).port;
    writeFileSync(join(agentDir, "models.json"), JSON.stringify({ providers: { [providerId]: {
      baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "fixture-not-a-real-credential", api: "openai-completions",
      models: [{ id: modelId, name: "Fixture", reasoning: false, input: ["text"], contextWindow: 32000, maxTokens: 1000,
        cost: { input: ["sdk-aggregate-retry","efficiency","metered-failure","toggle-usage"].includes(variant)?1:0, output: ["sdk-aggregate-retry","efficiency","metered-failure","toggle-usage"].includes(variant)?1:0, cacheRead: 0, cacheWrite: 0 } },...(["usage-task","efficiency"].includes(variant)?[{id:"fixture-alternative",name:"Alternative",reasoning:false,input:["text"],contextWindow:32000,maxTokens:1000,cost:{input:variant === "efficiency"?1:0,output:variant === "efficiency"?1:0,cacheRead:0,cacheWrite:0}}]:[])],
    } } }));
    writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [], compaction: { enabled: variant.startsWith("auto-compaction"), reserveTokens: variant.startsWith("auto-compaction") ? 1024 : 256, keepRecentTokens: variant.startsWith("auto-compaction") ? 1 : 100 },
      retry: { enabled: true, maxRetries: variant === "native-retry" || variant === "native-retry-after" ? 1 : 0, baseDelayMs: 10, provider: { maxRetries: variant === "sdk-aggregate-retry"?1:0, maxRetryDelayMs:variant === "sdk-aggregate-retry"?100:60000, timeoutMs: 10000 } },
      enableInstallTelemetry: false, quietStartup: true }));
    const config = configured(); if (["with-subagents", "mixed-parent-profile"].includes(variant)) config.features.managedWorkflows = true; config.storage.path = join(root, "state/runtime.db"); config.recovery.requestTimeoutMs = 10000;
    config.executionProfiles.interactive.timeoutMs = 10000;
    if (variant.endsWith("-timeout")) config.recovery.requestTimeoutMs = 500;
    if (variant === "wait-deadline") config.recovery.maxWaitMs = 500;
    if (variant === "mixed-parent-profile") config.executionProfiles.interactive.tools = ["kernel_task", "write"];
    config.routes.primary.provider = providerId; config.routes.primary.model = modelId; config.routes.primary.accountBinding = `provider:${providerId}`;
    if (sample) config.quotaGroups.pool.rules = sample.rules;
    if (variant === "compaction-history") config.quotaGroups.pool.baseIntervalMs = 60000;
    if (variant.startsWith("lifecycle-")) config.quotaGroups.pool.baseIntervalMs = 5000;
    if (variant.startsWith("canary")) config.recovery.lightCanaryEnabled = true;
    if (variant.startsWith("restart-")) config.quotaGroups.pool.baseIntervalMs = 2000;
    if(["usage-only","disabled","auto-off-with-rules","opinion-off"].includes(variant)) {
      config.enabled=variant!=="disabled";config.features.interactiveRecovery=false;config.modelPolicy.candidates=["primary"];config.modelPolicy.defaultPreference=["primary"];
      config.secondOpinion.model="primary";
    }
    if (["current-session","usage-task","efficiency"].includes(variant)) {
      config.recovery.primaryRoute = null; config.routes = {}; config.allowedRoutes = []; config.quotaGroups = {}; config.network = {};
      config.recovery.policies.legacy = {};
      config.recovery.policies.defaults = { ...config.recovery.policies.defaults, quotaBackoff:["100ms"], requestTimeout:"10s", positiveJitterRatio:0 };
    }
    const configPath = join(root, "task-keeper.json"); writeFileSync(configPath, JSON.stringify(config));
    const cli = fileURLToPath(new URL("../node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js", import.meta.url));
    let entry = fileURLToPath(new URL("../index.ts", import.meta.url));
    if(variant.startsWith("cut-continue-"))entry=join(nativeContinuationCut(fileURLToPath(new URL("..",import.meta.url)),root,variant.split("-")[2]),"index.ts");
    if (variant === "lost-ack") entry = join(continuationAckCut(fileURLToPath(new URL("..", import.meta.url)), root), "index.ts");
    if (variant === "without-subagents") {
      const source = fileURLToPath(new URL("..", import.meta.url)), copy = join(root, "standalone-package");
      cpSync(source, copy, { recursive: true, filter: (path) => !path.split("/").some((part) => ["node_modules", "test-results", "coverage"].includes(part)) });
      mkdirSync(join(copy, "node_modules/@earendil-works"), { recursive: true });
      for (const dependency of ["ajv", "typebox", "@earendil-works/pi-coding-agent"]) symlinkSync(join(source, "node_modules", dependency), join(copy, "node_modules", dependency));
      assert.equal(existsSync(join(copy, "node_modules/pi-subagents")), false); entry = join(copy, "index.ts");
    }
    const launch = (sessionId?: string) => spawn(process.execPath, [cli, "--mode", "rpc", "--no-extensions", ...(variant === "with-subagents" ? ["-e", fileURLToPath(new URL("../node_modules/pi-subagents/index.ts", import.meta.url))] : []), "-e", entry,
      "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline",
      "--provider", providerId, "--model", modelId, "--thinking", "off", "--tools", variant === "mixed-parent-profile" ? "kernel_task,write" : "read,write,edit",
      "--session-dir", join(root, "sessions"), ...(sessionId ? ["--session-id", sessionId] : [])], { cwd, stdio: ["pipe", "pipe", "pipe"], env: {
        PATH: process.env.PATH, LANG: "C.UTF-8", PI_CODING_AGENT_DIR: agentDir, PI_TASK_KEEPER_CONFIG: configPath,
        PI_OFFLINE: "1", PI_TELEMETRY: "0",
      } });
    let child = launch();
    const children = [child];
    let stderr = "", pending = "";
    const events: Array<Record<string, unknown>> = [];
    function watch() {
      child.stderr.on("data", (chunk) => { stderr = (stderr + chunk).slice(-12000); });
      child.stdout.on("data", (chunk) => {
      pending += chunk;
      let i: number;
      while ((i = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, i); pending = pending.slice(i + 1);
        try { events.push(JSON.parse(line)); } catch { stderr += `\nnon-JSON stdout: ${line}`; }
      }
      });
    }
    watch();
    t.after(async () => {
      for (const process of children) {
        if (process.exitCode === null && process.signalCode === null) { const exit = once(process, "exit"); process.kill("SIGTERM"); await exit; }
      }
      server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve()));
    });
    const send = (value: unknown) => child.stdin.write(`${JSON.stringify(value)}\n`);
    let restartedProcess: { beforePid: number; afterPid: number; before: RecoveryRecord; offline: RecoveryRecord; relaunchedAt: number; signal: string | null } | null = null;
    async function wait(predicate: () => boolean, description: string) {
      const until = Date.now() + 18000;
      while (!predicate()) {
        if (child.exitCode !== null || Date.now() > until) {
          throw new Error(`${description}; requests=${requests.length}; events=${JSON.stringify(events.slice(-8))}; stderr=${stderr}`);
        }
        await delay(10);
      }
    }
    let explicitUsageTask:string|null=null;
    send({ id: "state", type: "get_state" });
    await wait(() => events.some((event) => event.id === "state"), "Pi startup");
    if(variant === "toggle-usage"){
      send({id:"begin-toggle",type:"prompt",message:"/orch task begin --group toggle -- One task"});await wait(()=>events.some(event=>event.id==="begin-toggle"),"begin toggle task");
      const observer=new Store(join(root,"state"));try{const ledger=new UsageLedger(observer),policy=observer.list<RecoveryRecord>("recovery")[0].value.policyDigest;
        for(let index=0;index<3;index++){config.usage.enabled=index!==1;writeFileSync(configPath,JSON.stringify(config));send({id:`toggle-${index}`,type:"prompt",message:"Continue the same task"});await wait(()=>requests.length===index+1&&events.filter(event=>event.type==="agent_settled").length>=index+1,"toggle generation settles");}
        const row=ledger.query()[0];acceptance("AC12","toggle-mid-task",{level:"A",observer:"native-generations-around-trusted-usage-toggle",predicate:"collection gap cannot be presented as a cheaper complete task",artifact:observerArtifact("usage-toggle",{row,requests,events})},()=>{
          assert.equal(requests.length,3);assert.equal(row.generations,2);assert.equal(row.knownTokens.input+row.knownTokens.output,40);assert.equal(row.tokens.input,null);assert.equal(row.usageCoverage,null);assert.ok(row.task.gaps.includes("usage-disabled"));assert.equal(row.costs.USD.estimated,"0.00004");assert.equal(observer.list<RecoveryRecord>("recovery")[0].value.policyDigest,policy);
        });
      }finally{observer.close();}return;
    }
    if(variant === "efficiency"){
      const observer=new Store(join(root,"state"));try{const ledger=new UsageLedger(observer);
        for(const [label,rounds] of [["one",1],["many",5]] as const){
          if(label==="many"){send({id:"efficiency-model",type:"set_model",provider:providerId,modelId:"fixture-alternative"});await wait(()=>events.some(event=>event.id==="efficiency-model"),"second efficiency model");}
          send({id:`begin-${label}`,type:"prompt",message:`/orch task begin --group efficiency -- ${label}`});await wait(()=>events.some(event=>event.id===`begin-${label}`),"logical efficiency task");
          const task=ledger.query().find(row=>row.task.title===label)!.task;
          for(let round=0;round<rounds;round++){const expected=requests.length+1;send({id:`${label}-${round}`,type:"prompt",message:"Perform or continue the same synthetic fixture task"});await wait(()=>requests.length===expected&&events.filter(event=>event.type==="agent_settled").length>=expected,"metered logical round");}
          send({id:`finish-${label}`,type:"prompt",message:`/orch task finish ${task.id} --accept`});await wait(()=>events.some(event=>event.id===`finish-${label}`),"user accepts logical task");
        }
        const rows=ledger.query(),one=rows.find(row=>row.task.title==="one")!,many=rows.find(row=>row.task.title==="many")!;
        send({id:"manual-model-query",type:"prompt",message:"/orch models --group efficiency"});await wait(()=>events.some(event=>event.id==="manual-model-query"),"read-only model comparison");
        const comparison=events.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(String(event.message))];}catch{return[];}}).filter(value=>Array.isArray(value)&&value.some(row=>row.comparisonGroup==="efficiency")).at(-1);
        acceptance("AC14","manual-query",{level:"A",observer:"native-models-command-and-unchanged-receiver",predicate:"manual comparison uses task totals without another model call",artifact:observerArtifact("manual-model-query",{comparison,rows,requests})},()=>{
          assert.equal(requests.length,6);assert.equal(comparison.length,2);assert.ok(comparison.every((row:{started:number})=>row.started===1));assert.equal(comparison.find((row:{model:string})=>row.model.endsWith("fixture-alternative")).costPerAccepted,"0.000025");
        });
        acceptance("AC12","10x-vs-25x",{level:"A",observer:"six-real-Pi-generations-and-receiver-token-values",predicate:"one 10-unit task costs less than five 5-unit rounds",artifact:observerArtifact("ten-vs-twenty-five",{rows,requests,events})},()=>{
          assert.equal(requests.length,6);assert.equal(one.generations,1);assert.equal(many.generations,5);assert.equal(one.knownTokens.input+one.knownTokens.output,10);assert.equal(many.knownTokens.input+many.knownTokens.output,25);
          assert.equal(one.costs.USD.estimated,"0.00001");assert.equal(many.costs.USD.estimated,"0.000025");assert.equal(one.task.status,"accepted");assert.equal(many.task.status,"accepted");assert.equal(observer.db.prepare("SELECT count(*) n FROM intents").get()!.n,0);
        });
      }finally{observer.close();}return;
    }
    if(variant === "usage-task"){
      send({id:"begin-usage",type:"prompt",message:"/orch task begin --group recovery -- Logical task"});await wait(()=>events.some(event=>event.id==="begin-usage"),"explicit statistics begin");
      const observer=new Store(join(root,"state"));try{const task=new UsageLedger(observer).query()[0].task;explicitUsageTask=task.id;
        acceptance("AC11","begin",{level:"A",observer:"native-user-command-and-SQLite",predicate:"user task begins without a model request",artifact:observerArtifact("task-begin",{task,requests})},()=>{assert.equal(task.title,"Logical task");assert.equal(task.comparisonGroup,"recovery");assert.equal(task.temporary,false);assert.equal(requests.length,0);});
      }finally{observer.close();}
    }
    if (variant === "compaction-history") {
      send({ id: "prelude", type: "prompt", message: "Historical fixture context " + "previous context ".repeat(1200) });
      await wait(() => events.some((event) => event.type === "agent_settled"), "prelude settled"); events.length = 0;
    }
    send({ id: "prompt", type: "prompt", message: "Perform the synthetic fixture task; preserve completed actions." + ((variant === "write-before-limit" || variant === "compaction-history" || variant === "canary-false-positive") ? "\nLong context fixture: " + "preserved task context ".repeat(1000) : "") });
    if (variant === "lost-ack") {
      await wait(() => heldWrite !== null && existsSync(join(root,"ack-observations.jsonl")), "actual continuation reached receiver without an ACK");
      const observer = new Store(join(root,"state")); t.after(() => observer.close());
      const pendingRecord = observer.list<RecoveryRecord>("recovery")[0].value, firstIntent = pendingRecord.intentId!;
      send({id:"resume-without-ack",type:"prompt",message:"/throttle resume"}); await wait(() => events.some(event => event.id === "resume-without-ack"), "resume denied before reconciliation");
      for (const id of ["REC-021", "T40"]) evidence(id, () => {
        assert.notEqual(child.pid,process.pid); assert.equal(requests.length,2); assert.equal(pendingRecord.attempts,1);
        assert.equal(observer.intent(firstIntent)!.nativeId,null); assert.equal(observer.claims().length,1);
        assert.ok(JSON.stringify(events).includes("INTENT_RECONCILIATION_REQUIRED")); assert.equal(existsSync(join(cwd,"proof.txt")),false);
      });
      respond(heldWrite!,"tool"); heldWrite=null;
      await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.status === "DONE", "terminal reconciliation after lost ACK");
      const firstDone = observer.list<RecoveryRecord>("recovery")[0].value;
      send({id:"second-goal",type:"prompt",message:"Perform a second synthetic fixture goal after the completed execution."});
      await wait(() => requests.length >= 4, "second goal quota response");
      await wait(() => requests.length === 5 && observer.list<RecoveryRecord>("recovery")[0].value.status === "DONE", "another incident progresses after the old ACK listener ends");
      const last = observer.list<RecoveryRecord>("recovery")[0].value;
      const intents = observer.db.prepare("SELECT id,native_id,status FROM intents WHERE kind='continue' ORDER BY rowid").all();
      const observations = readFileSync(join(root,"ack-observations.jsonl"),"utf8").trim().split("\n").map(line=>JSON.parse(line));
      for (const id of ["REC-021", "T40"]) evidence(id, () => {
        assert.equal(firstDone.attempts,1); assert.equal(last.attempts,2); assert.equal(intents.length,2); assert.equal(last.scopeId,firstDone.scopeId);
        assert.ok(intents.every(intent => intent.status === "settled" && typeof intent.native_id === "string"));
        assert.ok(intents.every(intent => observations.some(value=>value.intent.id===intent.id&&value.nativeId===intent.native_id&&value.ackDelivered===false)));
        assert.equal(readFileSync(join(cwd,"proof.txt"),"utf8"),"once\n"); assert.equal(events.filter(event=>event.type==="tool_execution_start"&&event.toolName==="write").length,1);
        assert.equal(requests.length,5); assert.equal(observer.claims().length,0); assert.equal(last.history.length,2);
        assert.equal(observer.db.prepare("SELECT count(*) n FROM requests").get()!.n,0);
      });
      if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"ack-observers");mkdirSync(path,{recursive:true});
        writeFileSync(join(path,"lost-ack.json"),JSON.stringify({pendingRecord,firstDone,last,intents,observations,requests,receiverStatuses,events,manifest:JSON.parse(readFileSync(join(root,"ack-cut-manifest.json"),"utf8"))},null,2));}
      return;
    }
    if (variant.startsWith("lifecycle-")) {
      await wait(() => events.some(event => event.type === "agent_settled"), "quota waiting before lifecycle transition");
      const observer = new Store(join(root, "state")); t.after(() => observer.close());
      const before = observer.list<RecoveryRecord>("recovery")[0].value, owner = observer.owner(before.scopeId)!;
      assert.equal(before.status, "WAITING_QUOTA"); assert.equal(requests.length, 1); assert.ok(before.notBefore > Date.now());
      let lifecycle: Record<string, unknown>;
      if (variant === "lifecycle-fork") {
        send({id:"fork-targets",type:"get_fork_messages"}); await wait(() => events.some(event => event.id === "fork-targets"), "native fork entries");
        const reply = events.find(event => event.id === "fork-targets")!;
        assert.equal(reply.success, true); const entryId = (reply.data as {messages:Array<{entryId:string}>}).messages[0]?.entryId; assert.ok(entryId);
        lifecycle = {id:"lifecycle",type:"fork",entryId};
      } else if (variant === "lifecycle-switch") {
        const target = SessionManager.create(cwd, join(root, "target-sessions"));
        target.appendMessage({role:"user",content:"Independent seeded session",timestamp:Date.now()});
        target.appendMessage({role:"assistant",content:[{type:"text",text:"Seeded setup only; no network call"}],api:"openai-completions",provider:providerId,model:modelId,
          usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason:"stop",timestamp:Date.now()});
        assert.ok(existsSync(target.getSessionFile()!)); lifecycle = {id:"lifecycle",type:"switch_session",sessionPath:target.getSessionFile()};
      } else lifecycle = {id:"lifecycle",type:"new_session"};
      if (variant === "lifecycle-shutdown") { const exited = once(child, "exit"); child.kill("SIGTERM"); await exited; }
      else {
        send(lifecycle); await wait(() => events.some(event => event.id === "lifecycle"), "native lifecycle completes");
        assert.equal(events.find(event => event.id === "lifecycle")!.success, true);
        send({id:"new-context-status",type:"prompt",message:"/throttle status"}); await wait(() => events.some(event => event.id === "new-context-status"), "new context projection");
      }
      await delay(Math.max(0, before.notBefore - Date.now()) + 300);
      const after = observer.get<RecoveryRecord>("recovery", before.scopeId)!;
      const views = events.filter(event => event.type === "extension_ui_request" && event.method === "notify").flatMap(event => {try{return[JSON.parse(String(event.message))];}catch{return[];}});
      for (const id of ["REC-020", "T37"]) evidence(id, () => {
        assert.equal(requests.length, 1); assert.equal(after.status, "PAUSED"); assert.equal(after.attempts, 0);
        assert.equal(after.sessionId, before.sessionId); assert.deepEqual(after.history, before.history); assert.equal(after.notBefore, before.notBefore);
        assert.equal(observer.owner(before.scopeId)!.active, false); assert.ok(observer.owner(before.scopeId)!.epoch > owner.epoch);
        assert.equal(observer.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n, 0); assert.equal(observer.claims().length, 0);
        assert.equal(existsSync(join(cwd, "proof.txt")), false);
        if (variant !== "lifecycle-shutdown") { const current = views.filter(view => view.recovery).at(-1)!; assert.ok(current); assert.notEqual(current.recovery.sessionId, before.sessionId); assert.ok(["IDLE", "PAUSED"].includes(current.recovery.status)); assert.equal(current.recovery.attempts, 0); assert.equal(current.recovery.intentId, null); assert.deepEqual(current.recovery.history, []); }
        else assert.ok(child.exitCode !== null || child.signalCode !== null);
      });
      if(variant!=="lifecycle-new")acceptance("AC08",variant==="lifecycle-switch"?"switch":variant==="lifecycle-fork"?"fork":"shutdown",{level:"A",observer:"native-session-lifecycle-and-expired-callback-window",predicate:"lifecycle revokes old automatic control",artifact:observerArtifact(variant,{before,after,requests,events})},()=>{assert.equal(requests.length,1);assert.equal(after.status,"PAUSED");assert.equal(after.attempts,0);assert.equal(observer.owner(before.scopeId)!.active,false);});
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"lifecycle-observers");mkdirSync(path,{recursive:true});
        writeFileSync(join(path,`${variant}.json`),JSON.stringify({before,after,owner,ownerAfter:observer.owner(before.scopeId),events,views,requests,receiverStatuses,process:{pid:child.pid,exitCode:child.exitCode,signalCode:child.signalCode}},null,2)); }
      return;
    }
    if (variant === "wait-deadline") {
      await wait(() => events.some(event => event.type === "agent_settled"), "original limited execution settled");
      const observer = new Store(join(root, "state")); t.after(() => observer.close());
      const initial = observer.list<RecoveryRecord>("recovery")[0].value;
      assert.equal(initial.status, "WAITING_QUOTA"); assert.ok(initial.deadlineAt! < initial.notBefore);
      await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.status === "BLOCKED", "overall deadline preempts cooldown");
      const blocked = observer.list<RecoveryRecord>("recovery")[0].value;
      assert.notEqual(child.pid, process.pid); assert.equal(child.exitCode, null);
      assert.equal(observer.get<{identity:{pid:number}}>("owner-process", blocked.scopeId)!.identity.pid, child.pid);
      assert.equal(blocked.reason, "recovery_deadline_exhausted"); assert.equal(blocked.deadlineAt, initial.deadlineAt);
      assert.equal(blocked.notBefore, initial.notBefore); assert.equal(blocked.attempts, 0); assert.equal(blocked.intentId, null);
      assert.equal(requests.length, 1); assert.equal(observer.claims().length, 0); assert.deepEqual(blocked.history, initial.history);
      send({ id: "deadline-resume", type: "prompt", message: "/throttle resume" });
      await wait(() => events.some(event => event.id === "deadline-resume"), "resume command response");
      await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.status === "BLOCKED", "resume retains deadline");
      const after = observer.list<RecoveryRecord>("recovery")[0].value;
      acceptance("AC07","max-wait",{level:"A",observer:"native-Pi-and-receiver",predicate:"wall-clock wait deadline survives explicit resume",artifact:observerArtifact("max-wait",{initial,blocked,after,requests})},()=>{
        assert.equal(after.reason,"recovery_deadline_exhausted");assert.equal(after.deadlineAt,blocked.deadlineAt);assert.equal(requests.length,1);
      });
      assert.equal(after.reason, "recovery_deadline_exhausted"); assert.equal(after.deadlineAt, blocked.deadlineAt);
      assert.equal(after.incidentId, initial.incidentId); assert.equal(after.notBefore, initial.notBefore); assert.equal(requests.length, 1);
      await delay(Math.max(0, initial.notBefore - Date.now()) + 100); assert.equal(requests.length, 1);
      assert.equal(observer.list<RecoveryRecord>("recovery")[0].value.status, "BLOCKED");
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-observers"); mkdirSync(path, { recursive: true });
        writeFileSync(join(path, "wait-deadline.json"), JSON.stringify({ initial, blocked, after, receiverStatuses, events, observerPid: process.pid, piPid: child.pid }, null, 2));
      }
      return;
    }
    if (variant === "resume-cooldown") {
      await wait(() => events.some(event => event.type === "agent_settled"), "initial quota settlement");
      const observer = new Store(join(root, "state")); t.after(() => observer.close());
      const before = observer.list<RecoveryRecord>("recovery")[0].value;
      assert.equal(before.status, "WAITING_QUOTA"); assert.ok(before.notBefore > Date.now()); assert.equal(requests.length, 1);
      send({ id: "resume-wait", type: "prompt", message: "/throttle resume" });
      await wait(() => events.some(event => event.id === "resume-wait"), "explicit resume while cooldown remains");
      const after = observer.list<RecoveryRecord>("recovery")[0].value;
      for (const id of ["CFG-013", "REC-010"]) evidence(id, () => {
        assert.equal(after.status, "WAITING_QUOTA"); assert.equal(after.notBefore, before.notBefore); assert.equal(after.attempts, 0);
        assert.equal(after.incidentId, before.incidentId); assert.deepEqual(after.history, before.history); assert.equal(requests.length, 1);
      });
      await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.status === "DONE", "resume progresses after original cooldown");
      const completed = observer.list<RecoveryRecord>("recovery")[0].value;
      for (const id of ["CFG-013", "REC-010"]) evidence(id, () => {
        assert.equal(requests.length, 2); assert.equal(completed.attempts, 1); assert.equal(completed.scopeId, before.scopeId);
        assert.ok(requestTimes[1] - requestTimes[0] >= 4990); assert.equal(completed.intentId, null);
      });
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-observers"); mkdirSync(path, { recursive: true });
        writeFileSync(join(path, "resume-cooldown.json"), JSON.stringify({ before, afterResume: after, completed,
          requestOffsetsMs: requestTimes.map(time => time - requestTimes[0]) }, null, 2));
      }
      return;
    }
    if(variant.startsWith("cut-continue-")){
      const point=variant.split("-")[2];await wait(()=>existsSync(join(root,"continue-cut.json")),`actual continuation ${point}`);
      const observer=new Store(join(root,"state"));t.after(()=>observer.close());const before=observer.list<RecoveryRecord>("recovery")[0].value,marker=JSON.parse(readFileSync(join(root,"continue-cut.json"),"utf8")),id=before.intentId??marker.data?.id;
      const intent=id?observer.intent(id):null;
      if(point==="C0"){assert.equal(intent,null);assert.equal(requests.length,1);}else if(point==="C1"){assert.equal(intent!.status,"prepared");assert.equal(requests.length,1);}else if(point==="C2"||point==="C3")assert.equal(intent!.nativeId,null);else assert.ok(intent!.nativeId);
      const oldPid=child.pid,exited=once(child,"exit");child.kill("SIGKILL");await exited;await delay(200);const afterStopRequests=requests.length;
      child=launch(before.sessionId);children.push(child);pending="";watch();send({id:"continue-cut-restarted",type:"get_state"});await wait(()=>events.some(event=>event.id==="continue-cut-restarted"),"restart after continuation cut");
      if(["C0","C4","C5"].includes(point))await wait(()=>observer.list<RecoveryRecord>("recovery")[0].value.status==="DONE","completed continuation is reconciled");else await delay(300);
      const after=observer.list<RecoveryRecord>("recovery")[0].value;
      acceptance("AC27",`continue.${point}`,{level:"P",observer:"actual-Pi-continuation-cut-and-restarted-ledger",predicate:`continue.${point} preserves native identity without blind replay`,artifact:observerArtifact(`continue-${point}`,{before,after,marker,intent,afterStopRequests,requests,events,oldPid,newPid:child.pid,claims:observer.claims()})},()=>{
        assert.equal(after.scopeId,before.scopeId);assert.ok(after.ownerEpoch>before.ownerEpoch);assert.notEqual(child.pid,oldPid);
        if(["C0","C4","C5"].includes(point)){assert.equal(after.status,"DONE");assert.equal(requests.length,2);assert.equal(observer.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n,1);assert.equal(observer.claims().length,0);}
        else {assert.equal(after.status,"PAUSED");assert.equal(requests.length,afterStopRequests);assert.equal(after.intentId,before.intentId);assert.ok(observer.claims().length>0);}
      });return;
    }
    if(variant === "explicit-zero"){
      await wait(()=>requests.length===1&&events.some(event=>event.type==="agent_settled"),"explicit zero metering");
      const observer=new Store(join(root,"state"));try{const fact=new UsageLedger(observer).facts()[0];assert.equal(fact.tokens.input,0);assert.equal(fact.tokens.output,0);assert.equal(fact.coverage,"aggregate");assert.equal(fact.notSent,undefined);assert.equal(fact.cost.kind,"unknown");assert.equal(requests.length,1);}finally{observer.close();}return;
    }
    if(variant === "metered-failure"){
      await wait(()=>requests.length===1&&events.some(event=>event.type==="agent_settled"),"metered truncated generation");await delay(200);assert.equal(requests.length,1);
      send({id:"retry-metered",type:"prompt",message:"Continue the same synthetic fixture task after the truncated result"});await wait(()=>requests.length===2&&events.filter(event=>event.type==="agent_settled").length>=2,"explicit retry complete");
      const observer=new Store(join(root,"state"));try{const ledger=new UsageLedger(observer),row=ledger.query()[0],facts=ledger.facts();
        acceptance("AC12","failed-retry",{level:"A",observer:"native-truncated-generation-and-successful-retry",predicate:"failed generation's nonzero usage remains in task total",artifact:observerArtifact("metered-failure",{row,facts,requests,events})},()=>{
          assert.equal(row.generations,2);assert.equal(row.failedGenerations,1);assert.equal(row.successfulGenerations,1);assert.equal(row.knownTokens.input+row.knownTokens.output,160);assert.equal(row.costs.USD.estimated,"0.00016");
          assert.equal(facts.find(f=>f.outcome==="failure")!.tokens.input,100);assert.equal(ledger.query().length,1);assert.equal(requests.length,2);
        });
      }finally{observer.close();}return;
    }
    if(variant === "queued-tail"){
      await wait(()=>heldWrite!==null,"initial request before queued follow-up");
      send({id:"queued-follow-up",type:"prompt",message:"QUEUED_FOLLOW_UP: continue from the current task",streamingBehavior:"followUp"});
      await wait(()=>events.some(event=>event.id==="queued-follow-up"),"queued input acknowledged");
      heldWrite!.writeHead(429,{"content-type":"application/json"});heldWrite!.end('{"error":{"message":"quota before queued work","code":"rate_limit"}}');
      await wait(()=>events.some(event=>event.type==="agent_settled"),"native queue settles");await delay(300);
      const observer=new Store(join(root,"state"));try{const state=observer.list<RecoveryRecord>("recovery")[0].value;
        acceptance("AC06","queued-tail",{level:"A",observer:"real-native-follow-up-queue-and-receiver",predicate:"pending user work cannot become an outer continuation",artifact:observerArtifact("queued-tail",{state,events,requests})},()=>{
          assert.equal(state.attempts,0);assert.equal(observer.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n,0);
          assert.ok(requests.length<=2);if(requests.length===2)assert.ok(JSON.stringify(requests[1].messages).includes("QUEUED_FOLLOW_UP"));assert.ok(observer.list("native-errors").length>0);
        });
        acceptance("AC08","input",{level:"A",observer:"actual-queued-user-input-and-no-outer-intent",predicate:"new user input cannot become an autonomous continuation",artifact:observerArtifact("input-revocation",{state,requests,events})},()=>{assert.equal(state.attempts,0);assert.equal(observer.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n,0);});
      }finally{observer.close();}return;
    }
    if (variant === "stream-error" || variant === "stream-truncated") {
      await wait(()=>requests.length>=2&&events.filter(event=>event.type==="agent_settled").length>=2,"failed recovery stream settled");
      const observer=new Store(join(root,"state"));t.after(()=>observer.close());const record=observer.list<RecoveryRecord>("recovery")[0].value;
      send({id:"stream-status",type:"prompt",message:"/throttle status"});await wait(()=>events.some(event=>event.id==="stream-status"),"stream failure UI");
      const ui=events.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(String(event.message))];}catch{return[];}}).filter(value=>value.recovery).at(-1);
      acceptance("AC06",variant === "stream-error"?"stream-error":"truncated",{level:"A",observer:"native-terminal-and-HTTP-receiver",predicate:"HTTP 200 does not turn failed stream into completion",artifact:observerArtifact(variant,{record,events,receiverStatuses,ui})},()=>{
        assert.notEqual(record.status,"DONE");assert.equal(record.attempts,1);assert.ok(record.history.length>=2);assert.notEqual(ui.recovery.status,"DONE");
      });
      matrixCase("stream-terminals",variant === "stream-error" ? "error" : "truncated",()=>{
        assert.equal(streamHeadersSent,true);assert.deepEqual(receiverStatuses.map(item=>item.status),[429,200]);assert.equal(requests.length,2);
        assert.notEqual(record.status,"DONE");assert.equal(record.attempts,1);assert.ok(record.history.length>=2);assert.equal(observer.get<{status:string}>("incidents","pool")!.status,"OPEN");
        assert.notEqual(ui.recovery.status,"DONE");assert.equal(ui.recovery.scopeId,record.scopeId);
        const ended=events.filter(event=>event.type==="message_end").map(event=>event.message as {role:string;stopReason?:string;errorMessage?:string}).filter(message=>message.role==="assistant").at(-1)!;
        assert.notEqual(ended.stopReason,"stop");assert.ok(ended.errorMessage);if(variant === "stream-error")assert.ok(ended.errorMessage!.includes("STREAM_INNER_ERROR"));
      });
      send({id:"stream-pause",type:"prompt",message:"/throttle pause"});await wait(()=>events.some(event=>event.id==="stream-pause"),"hold future retries");
      send({id:"stream-explain",type:"prompt",message:"Explain the previous stream failure from the retained context"});await wait(()=>requests.length===3,"next real parent input contains failure context");
      matrixCase("stream-terminals",variant === "stream-error" ? "error" : "truncated",()=>{
        const context=JSON.stringify(requests[2].messages);assert.ok(context.includes("nativeFailures"));assert.ok(context.includes("totalFailures"));
        if(variant === "stream-error")assert.ok(context.includes("STREAM_INNER_ERROR"));else assert.ok(context.includes("Stream ended without finish_reason"));
      });
      for(const id of ["REC-017","T23"])evidence(id,()=>{
        const ended=events.filter(event=>event.type==="message_end").map(event=>event.message as {role:string;stopReason?:string;errorMessage?:string}).filter(message=>message.role==="assistant").find(message=>message.errorMessage?.includes(variant==="stream-error"?"STREAM_INNER_ERROR":"Stream ended without finish_reason"));
        assert.ok(ended);assert.notEqual(ended.stopReason,"stop");assert.equal(receiverStatuses[1].status,200);
        assert.notEqual(record.status,"DONE");assert.equal(record.attempts,1);assert.notEqual(ui.recovery.status,"DONE");
        assert.equal(observer.get<{status:string}>("incidents","pool")!.status,"OPEN");assert.ok(JSON.stringify(requests[2].messages).includes(ended.errorMessage!));
      });
      if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"recovery-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,`${variant}.json`),JSON.stringify({record,ui,requests,receiverStatuses,events},null,2));}return;
    }
    if (variant.endsWith("-timeout")) {
      await wait(() => heldWrite !== null, "recovery request reached independent receiver");
      await wait(() => {
        const observer = new Store(join(root, "state"));
        try { return observer.list<RecoveryRecord>("recovery")[0]?.value.status === "BLOCKED"; }
        finally { observer.close(); }
      }, "finite request timeout during unlimited quota wait");
      await wait(() => timedOutConnectionClosed, "actual aborted recovery connection closed");
      const observer = new Store(join(root, "state")); t.after(() => observer.close());
      if (variant === "canary-timeout") await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.reason === "canary_termination_unknown", "canary returns its explicit uncertain termination observation");
      const record = observer.list<RecoveryRecord>("recovery")[0].value;
      assert.equal(record.reason, variant === "canary-timeout" ? "canary_termination_unknown" : "request_timeout_termination_unknown");
      assert.equal(config.recovery.maxWaitMs, null); assert.equal(requests.length, 2);
      assert.equal(observer.owner(record.scopeId)!.active, false);
      await delay(700); assert.equal(requests.length, 2);
      if(variant === "stream-timeout") matrixCase("stream-terminals","timeout",()=>{
        assert.equal(streamHeadersSent,true);assert.ok(events.some(event=>JSON.stringify(event).includes("STREAM_TIMEOUT_PARTIAL")));assert.equal(timedOutConnectionClosed,true);
        assert.equal(record.status,"BLOCKED");assert.equal(record.attempts,1);assert.equal(requests.length,2);assert.equal(observer.owner(record.scopeId)!.active,false);
      });
      if(variant === "request-timeout")acceptance("AC07","request-timeout",{level:"A",observer:"native-Pi-aborted-HTTP-connection",predicate:"finite timeout revokes automatic recovery",artifact:observerArtifact("request-timeout",{record,requests,timedOutConnectionClosed})},()=>{
        assert.equal(record.status,"BLOCKED");assert.equal(requests.length,2);assert.equal(timedOutConnectionClosed,true);assert.equal(observer.owner(record.scopeId)!.active,false);
      });
      if (variant === "canary-timeout") {
        assert.ok(record.intentId); assert.equal(observer.intent(record.intentId!)!.status, "unknown"); assert.ok(observer.claims().length > 0);
        send({ id: "timeout-resume", type: "prompt", message: "/throttle resume" });
        await wait(() => events.some(event => event.id === "timeout-resume"), "unknown canary blocks explicit resume");
        assert.equal(requests.length, 2); assert.equal(observer.list<RecoveryRecord>("recovery")[0].value.status, "BLOCKED");
      } else {
        await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.intentId === null, "native settled proof releases timed-out continuation");
        assert.equal(observer.claims().length, 0);
        send({ id: "timeout-resume", type: "prompt", message: "/throttle resume" });
        await wait(() => observer.list<RecoveryRecord>("recovery")[0].value.status === "DONE", "explicit resume after confirmed termination");
        assert.equal(requests.length, 3); assert.equal(observer.list<RecoveryRecord>("recovery")[0].value.attempts, 2);
      }
      if(variant === "stream-timeout" && process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"recovery-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"stream-timeout.json"),JSON.stringify({atTimeout:record,afterExplicitResume:observer.list<RecoveryRecord>("recovery")[0].value,streamHeadersSent,timedOutConnectionClosed,requests,receiverStatuses,events},null,2));}
      return;
    }
    if (variant === "pause-late-write") {
      await wait(() => heldWrite !== null, "owned recovery request before late write");
      send({ id: "pause-inflight", type: "prompt", message: "/throttle pause" });
      await wait(() => events.some(event => event.id === "pause-inflight"), "human pause");
      respond(heldWrite!, "tool"); heldWrite = null;
      await wait(() => {
        const observer = new Store(join(root, "state"));
        try { const value = observer.list<RecoveryRecord>("recovery")[0]?.value; return value?.status === "PAUSED" && value.intentId === null; }
        finally { observer.close(); }
      }, "paused owned turn physically settled");
      for (const id of ["REC-019", "T35"]) evidence(id, () => {
        assert.equal(existsSync(join(cwd, "proof.txt")), false); assert.equal(requests.length, 2);
      });
      send({ id: "resume-owned", type: "prompt", message: "/throttle resume" });
    }
    if (variant.startsWith("restart-")) {
      await wait(() => events.some((event) => event.type === "agent_settled"), "first quota wait");
      const beforeStore = new Store(join(root, "state"));
      t.after(() => beforeStore.close());
      const before = beforeStore.list<RecoveryRecord>("recovery")[0].value;
      assert.equal(before.status, "WAITING_QUOTA"); assert.equal(requests.length, 1);
      assert.ok(Date.now() < before.notBefore, "parent must exit during the original cooldown");
      const priorPid = child.pid!, exited = once(child, "exit"); child.kill("SIGKILL"); await exited;
      const signal = child.signalCode;
      // Observe from the receiver process while there is no Pi parent. Crossing
      // the persisted floor must not dispatch work or mutate the recovery ledger.
      const stopped = beforeStore.get<RecoveryRecord>("recovery", before.scopeId)!;
      const stoppedOwner = beforeStore.owner(before.scopeId);
      if (variant === "restart-overdue") await delay(Math.max(0, before.notBefore - Date.now()) + 150);
      const offline = beforeStore.get<RecoveryRecord>("recovery", before.scopeId)!;
      const relaunchedAt = Date.now();
      for (const id of ["REC-009", "TK11"]) evidence(id, () => {
        assert.equal(signal, "SIGKILL"); assert.equal(requests.length, 1);
        assert.equal(stopped.status, "WAITING_QUOTA"); assert.equal(stopped.intentId, null);
        assert.equal(stopped.notBefore, before.notBefore); assert.deepEqual(offline, stopped);
        assert.deepEqual(beforeStore.owner(before.scopeId), stoppedOwner);
        assert.equal(beforeStore.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0);
        assert.equal(beforeStore.claims().length, 0);
        if (variant === "restart-overdue") assert.ok(relaunchedAt > before.notBefore);
        else assert.ok(relaunchedAt < before.notBefore, "retain the before-floor restart variant");
      });
      pending = ""; child = launch(before.sessionId); children.push(child); watch();
      restartedProcess = {beforePid:priorPid,afterPid:child.pid!,before,offline,relaunchedAt,signal};
      send({ id: "state-restarted", type: "get_state" });
      await wait(() => events.some((event) => event.id === "state-restarted"), "restored Pi startup");
    }
    if (variant === "compaction-history") {
      await wait(() => events.some((event) => event.type === "agent_settled"), "quota terminal before compaction");
      send({ id: "compact", type: "compact", customInstructions: "Keep the fixture task scope." });
      await wait(() => events.some((event) => event.id === "compact"), "manual compaction response");
      const compacted = events.find((event) => event.id === "compact"); assert.equal(compacted?.success, true, JSON.stringify(compacted));
      send({ id: "after-compact", type: "prompt", message: "Report the retained quota failure after compaction." });
    }
    if (variant === "status-countdown") {
      const statuses = () => events.filter(event => event.type === "extension_ui_request" && event.method === "setStatus" && event.statusKey === "task-keeper");
      await wait(() => statuses().filter(event => typeof event.statusText === "string" && event.statusText.includes("WAITING_QUOTA")).length >= 2, "countdown refresh");
      const waits = statuses().filter(event => typeof event.statusText === "string" && event.statusText.includes("WAITING_QUOTA")).map(event => String(event.statusText));
      assert.equal(new Set(waits).size, waits.length); assert.ok(waits.every(text => text.includes("wait >=") && text.includes("attempts 0")));
      assert.equal(requests.length, 1);
      send({ id: "pause-status", type: "prompt", message: "/throttle pause" });
      await wait(() => events.some(event => event.id === "pause-status") && String(statuses().at(-1)?.statusText).includes("PAUSED"), "immediate paused status");
      const pausedAt = statuses().length; await delay(1100); assert.equal(statuses().length, pausedAt); assert.equal(requests.length, 1);
      const savedConfig = JSON.parse(readFileSync(configPath, "utf8")); savedConfig.enabled = false; writeFileSync(configPath, JSON.stringify(savedConfig));
      send({ id: "disable-status", type: "new_session" }); await wait(() => events.some(event => event.id === "disable-status"), "disabled new session");
      assert.equal(statuses().at(-1)?.statusText, undefined); assert.equal(requests.length, 1);
      return;
    }
    if(["usage-only","disabled","auto-off-with-rules","opinion-off"].includes(variant)) {
      await wait(()=>requests.length===1 && events.some(event=>event.type==="agent_settled"),"single ordinary generation");
      const exists=existsSync(join(root,"state/runtime.db"));let rows:unknown[]=[];
      if(exists){const observer=new Store(join(root,"state"));try{rows=new UsageLedger(observer).query();assert.equal(observer.list("recovery").length,0);assert.equal(observer.list("managed-jobs").length,0);}finally{observer.close();}}
      send({id:"usage-query",type:"prompt",message:"/orch usage"});await wait(()=>events.some(event=>event.id==="usage-query"),"usage command");
      if(variant === "usage-only"){
        const view:any=events.filter(e=>e.type==="extension_ui_request"&&e.method==="notify").flatMap(e=>{try{return[JSON.parse(String(e.message))];}catch{return[];}}).find(e=>Array.isArray(e)&&e[0]?.task);
        acceptance("AC33","unknown-cost",{level:"A",observer:"actual-usage-command-and-SDK-cost-provenance",predicate:"catalog zero without quote stays visibly unknown",artifact:observerArtifact("unknown-cost-view",{view,rows,requests})},()=>{assert.ok(view);assert.deepEqual(view,rows);assert.ok((view[0] as any).unknownCosts>0);assert.equal(Object.keys((view[0] as any).costs).length,0);assert.equal(requests.length,1);});
      }
      acceptance("AC02",variant,{level:"A",observer:"native-Pi-and-loopback-receiver",predicate:"independent switches send only the user's generation",artifact:observerArtifact(`switch-${variant}`,{requests,events,rows,exists})},()=>{
        assert.equal(requests.length,1);assert.equal(exists,variant!=="disabled");assert.equal(rows.length,variant==="disabled"?0:1);
        assert.equal(config.modelPolicy.automaticSelection,false);assert.equal(config.secondOpinion.enabled,false);
      });return;
    }
    const expectedRequests = variant === "auto-compaction" ? 5 : variant === "pause-late-write" || variant === "auto-compaction-failure" ? 4 : blockedService ? 1 : variant === "compaction-history" ? 5 : variant === "canary-false-positive" ? 5 : variant === "canary" || variant === "write-before-limit" ? 3 : 2;
    await wait(() => requests.length >= expectedRequests && events.some((event) => event.type === "agent_settled"), "bounded recovery");
    await wait(() => {
      const db = new Store(join(root, "state"));
      try { return db.list<RecoveryRecord>("recovery").some((entry) => entry.value.status === (variant === "auto-compaction-failure" ? "PAUSED" : blockedService ? "BLOCKED" : "DONE") && (variant !== "auto-compaction-failure" || entry.value.intentId === null)); }
      finally { db.close(); }
    }, "recovery terminal record");
    const observer = new Store(join(root, "state"));
    const record = observer.list<RecoveryRecord>("recovery")[0].value;
    const finalCanaryIncident = variant === "canary-false-positive" ? observer.get<{status: string}>("incidents", "pool") : null;
    if (variant === "native-retry-after") assert.ok(observer.list("request-denials").length > 0);
    if (variant === "native-retry") assert.ok(observer.list("native-errors").length > 0);
    if(variant === "native-retry"){
      send({id:"native-retry-status",type:"prompt",message:"/throttle status"});await wait(()=>events.some(event=>event.id==="native-retry-status"),"native retry completion UI");
      const ui=events.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(String(event.message))];}catch{return[];}}).filter(value=>value.recovery).at(-1);
      for(const id of ["REC-006","T18"])evidence(id,()=>{
        assert.deepEqual(receiverStatuses.map(item=>item.status),[429,200]);assert.equal(requests.length,2);
        assert.equal(record.status,"DONE");assert.equal(record.attempts,0);assert.equal(record.intentId,null);
        assert.equal(observer.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n,0);assert.equal(observer.claims().length,0);
        assert.equal(events.filter(event=>event.type==="auto_retry_start").length,1);assert.equal(events.filter(event=>event.type==="auto_retry_end").length,1);
        assert.equal(ui.recovery.status,"DONE");assert.equal(ui.recovery.attempts,0);assert.ok(ui.nativeFailures.total>0);
        for(const request of requests)assert.equal((request.messages as Array<{role:string;content:unknown}>).filter(message=>message.role==="user"&&JSON.stringify(message.content).includes("Perform the synthetic fixture task")).length,1);
      });
      if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"recovery-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"native-retry.json"),JSON.stringify({record,ui,requests,receiverStatuses,events},null,2));}
    }
    if(["retry-after","canary","canary-false-positive"].includes(variant)){
      const intents=observer.db.prepare("SELECT kind,status,payload,native_id FROM intents WHERE kind IN ('continue','canary')").all();
      for(const id of variant==="retry-after"?["REC-008","REC-010"]:variant==="canary"?["REC-016"]:["REC-015","REC-018","T22"])evidence(id,()=>{
        assert.ok(child.pid);assert.equal(child.exitCode,null);assert.equal(record.status,"DONE");assert.equal(observer.claims().length,0);
        assert.equal(intents.length,variant==="canary-false-positive"?4:variant==="canary"?2:1);
        assert.ok(intents.every(intent=>intent.status==="settled"&&JSON.parse(String(intent.payload)).incidentId===record.incidentId));
        if(variant==="retry-after"){
          assert.ok(requestTimes[1]-requestTimes[0]>=1000);assert.equal(intents[0].kind,"continue");
          assert.equal(record.history[0].retryAt,record.notBefore);assert.deepEqual(receiverStatuses.map(item=>item.status),[429,200]);
        }else{
          assert.equal(intents.filter(intent=>intent.kind==="canary").length,variant==="canary"?1:2);
          assert.equal(intents.filter(intent=>intent.kind==="continue").length,variant==="canary"?1:2);
          assert.ok(JSON.stringify(requests[1].messages).length<1000);assert.equal(JSON.stringify(requests[1].messages).includes("synthetic fixture task"),false);
        }
      });
      if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"recovery-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,`${variant}-process.json`),JSON.stringify({pid:child.pid,record,intents,requests,receiverStatuses,requestTimes},null,2));}
    }

    if (variant === "network-recovery") {
      assert.equal(record.history[0].category, "network_overload"); assert.equal(record.networkAttempts, 1);
      assert.equal(observer.list("incidents").length, 0);
      assert.equal(observer.get<{ status: string }>("transport-incidents", config.routes.primary.transportDomain)?.status, "CLOSED");
    }
    observer.close();
    if (variant === "mixed-parent-profile") {
      send({ id: "profile-doctor", type: "prompt", message: "/orch doctor" });
      await wait(() => events.some(event => event.id === "profile-doctor"), "profile diagnosis");
      const diagnosis = events.flatMap(event => { try { return event.method === "notify" ? [JSON.parse(String(event.message))] : []; } catch { return []; } }).find(value => value.adapter?.blockedReasons);
      assert.equal(record.status, "BLOCKED"); assert.equal(record.reason, "adapter_not_certified"); assert.equal(record.attempts, 0); assert.equal(requests.length, 1);
      assert.deepEqual(diagnosis?.adapter.blockedReasons, ["mixed_parent_mutation_profile_not_certified"]);
      assert.equal(existsSync(join(cwd, "proof.txt")), false); return;
    }
    if (errorCase[variant]) {
      if (blockedService) {
        send({ id: "blocked-resume", type: "prompt", message: "/throttle resume" });
        await wait(() => events.some(event => event.id === "blocked-resume"), "blocked resume response");
      }
      for (const id of ids[variant].split(" ")) evidence(id, () => {
        assert.equal(record.history[0].category, sample.expected); assert.equal(record.history.length, 1);
        assert.equal(record.status, blockedService ? "BLOCKED" : "DONE"); assert.equal(requests.length, blockedService ? 1 : 2);
        assert.equal(record.attempts, blockedService ? 0 : 1);
        assert.equal(record.history[0].evidence?.uncertain, ["service-hour-unknown", "service-unknown"].includes(variant));
        if (variant === "service-hour-known") {
          assert.ok(requestTimes[1] - requestTimes[0] >= 990);
          assert.equal(record.history[0].evidence?.categorySource, "binding-rule"); assert.ok(record.history[0].evidence?.retryAfterAt);
        }
        if (variant === "service-hour-unknown") { assert.equal(record.reason, "quota_reset_unknown"); assert.equal(record.history[0].retryAt, null); }
        if (variant === "service-auth") assert.equal(record.history[0].evidence?.categorySource, "http-status");
      });
      return;
    }
    if (service) for (const id of ["CFG-002", "REC-002", "TK10"]) evidence(id, () => {
      assert.equal(record.status, "DONE"); assert.equal(record.history[0].category, "resource_pressure");
      assert.equal(record.history[0].evidence?.categorySource, "binding-rule"); assert.equal(record.history[0].evidence?.uncertain, false);
      assert.equal(record.attempts, 1); assert.equal(requests.length, 2); assert.ok(requests.every(request => request.model === modelId));
      assert.ok(record.scopeId); assert.ok(record.sessionId); assert.equal(record.routeId, "primary");
    });
    if (variant === "observed-usage") for (const id of ["REC-003", "T20"]) evidence(id, () => {
      assert.equal(record.status, "DONE"); assert.equal(record.history[0].category, "resource_pressure");
      assert.equal(record.history[0].evidence?.categorySource, "binding-rule"); assert.equal(record.history[0].evidence?.uncertain, false);
      assert.equal(record.history[0].code, "throttling"); assert.equal(record.attempts, 1); assert.equal(requests.length, 2);
      assert.match(record.history[0].message, /usage allocated quota exceeded/);
    });
    assert.equal(requests.length, expectedRequests);
    assert.equal(record.attempts, variant === "native-retry" || variant === "sdk-aggregate-retry" || variant === "compaction-history" ? 0 : variant === "canary-false-positive" || variant === "pause-late-write" ? 2 : 1);
    assert.equal(record.history.length, variant === "native-retry" || variant === "sdk-aggregate-retry" ? 0 : variant === "canary-false-positive" ? 2 : 1);
    if (variant === "auto-compaction-failure") {
      const evidenceStore = new Store(join(root, "state"));
      try { for (const id of ["REC-007", "T19"]) evidence(id, () => {
        assert.equal(record.status, "PAUSED"); assert.equal(record.reason, "context_compaction_failed"); assert.equal(record.intentId, null);
        assert.equal(requests.length, 4); assert.equal(record.attempts, 1); assert.equal(readFileSync(join(cwd, "proof.txt"), "utf8"), "once\n");
        assert.ok(evidenceStore.list<{status:string;error?:string}>("context-operations").some(row => row.value.status === "failed" && row.value.error));
        assert.ok(evidenceStore.list<{source?:string;category:string}>("native-errors").some(row => row.value.source === "compaction" && row.value.category === "frequency_limit"));
        assert.ok(events.some(event => event.type === "compaction_end" && event.errorMessage));
      }); } finally { evidenceStore.close(); }
      return;
    }
    if (variant === "auto-compaction") for (const id of ["REC-007", "T19"]) evidence(id, () => {
      assert.equal(requests.length, 5); assert.equal(record.status, "DONE"); assert.equal(record.attempts, 1);
      assert.ok(JSON.stringify(requests[3].messages).includes("structured context checkpoint"));
      assert.ok(JSON.stringify(requests[4].messages).includes("PREFIX of a turn"));
      assert.equal((requests[3].tools as unknown[] | undefined)?.length ?? 0, 0); assert.equal((requests[4].tools as unknown[] | undefined)?.length ?? 0, 0);
      assert.equal(readFileSync(join(cwd, "proof.txt"), "utf8"), "once\n");
      assert.ok(events.some(event => event.type === "compaction_end" && event.aborted !== true && !event.errorMessage));
    });
    if(variant === "auto-compaction"){
      const observer=new Store(join(root,"state"));try{const facts=new UsageLedger(observer).facts().filter(f=>f.role==="compaction");
        acceptance("AC10","auxiliary",{level:"A",observer:"native-compaction-entry-usage-and-HTTP-receiver",predicate:"summary call usage is included without per-request fabrication",artifact:observerArtifact("auxiliary-usage",{facts,events,requests})},()=>{
          assert.equal(facts.length,1);assert.equal(facts[0].source,"native-operation-aggregate");assert.equal(facts[0].tokens.input,20);assert.equal(facts[0].tokens.output,20);assert.equal(facts[0].attemptIds.length,2);
        });
        const row=new UsageLedger(observer).query()[0];acceptance("AC12","compaction",{level:"A",observer:"native-summary-usage-in-whole-task-subtotals",predicate:"auxiliary consumption contributes to original task total",artifact:observerArtifact("compaction-task-total",{row,facts})},()=>{assert.equal(row.byRole.compaction.knownTokens.input,20);assert.equal(row.byRole.compaction.knownTokens.output,20);assert.equal(row.rounds.compaction,1);assert.equal(row.knownTokens.input,62020);});
      }finally{observer.close();}
    }
    if(variant === "pause-late-write")acceptance("AC08","late-return",{level:"A",observer:"late-native-tool-call-and-real-file-write-count",predicate:"late response cannot execute under revoked model authority",artifact:observerArtifact("late-return",{record,requests,events,effect:readFileSync(join(cwd,"proof.txt"),"utf8")})},()=>{assert.equal(readFileSync(join(cwd,"proof.txt"),"utf8"),"once\n");assert.equal(events.filter(event=>event.type==="tool_execution_end"&&event.toolName==="write"&&event.isError!==true).length,1);});
    if (variant === "pause-late-write") for (const id of ["REC-019", "T35"]) evidence(id, () => {
      assert.equal(record.status, "DONE"); assert.equal(record.attempts, 2); assert.equal(requests.length, 4);
      assert.equal(readFileSync(join(cwd, "proof.txt"), "utf8"), "once\n");
      assert.equal(events.filter(event => event.type === "tool_execution_end" && event.toolName === "write" && event.isError !== true).length, 1);
    });
    if (variant === "retry-after" || variant === "native-retry-after") assert.ok(requestTimes[1] - requestTimes[0] >= 990, "receiver observed a request before server cooldown");
    if(variant === "outer-recovery") {
      send({id:"stream-complete-status",type:"prompt",message:"/throttle status"});await wait(()=>events.some(event=>event.id==="stream-complete-status"),"completed recovery UI");
      const ui=events.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(String(event.message))];}catch{return[];}}).filter(value=>value.recovery).at(-1);
      const observer=new Store(join(root,"state"));try{matrixCase("stream-terminals","complete",()=>{
        assert.deepEqual(receiverStatuses.map(item=>item.status),[429,200]);assert.equal(record.status,"DONE");assert.equal(record.attempts,1);assert.equal(record.intentId,null);assert.equal(observer.claims().length,0);
        assert.equal(observer.get<{status:string}>("incidents","pool")!.status,"CLOSED");assert.equal(ui.recovery.status,"DONE");
        assert.ok(events.some(event=>event.type==="message_end"&&(event.message as {stopReason?:string}).stopReason==="stop"));assert.equal(observer.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue' AND status='settled'").get()!.n,1);
      });}finally{observer.close();}
      if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"recovery-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"stream-complete.json"),JSON.stringify({record,ui,requests,receiverStatuses,events},null,2));}
    }
    if (variant === "canary-false-positive" && process.env.TASK_KEEPER_TEST_RECORD_DIR) {
      const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-observers"); mkdirSync(path, { recursive: true });
      writeFileSync(join(path, "canary-false-positive.json"), JSON.stringify({ source: "Q2-loopback", requests, receiverStatuses,
        requestOffsetsMs: requestTimes.map(time => time - requestTimes[0]), canaryTransitions, finalRecord: record, finalIncident: finalCanaryIncident,
        nativeEvents: events.filter(event => ["agent_settled", "message_end"].includes(String(event.type))) }, null, 2));
    }
    if (variant === "canary-false-positive") for (const id of ["REC-015", "REC-018", "T22"]) evidence(id, () => {
      assert.equal(record.status, "DONE"); assert.equal(requests.length, 5); assert.equal(record.attempts, 2); assert.equal(record.canaryAttempts, 2);
      assert.deepEqual(receiverStatuses.map(item => item.status), [429, 200, 429, 200, 200]); assert.equal(finalCanaryIncident!.status, "CLOSED");
      for (const index of [0, 2, 4]) { assert.ok(JSON.stringify(requests[index].messages).length > 20000); assert.ok(JSON.stringify(requests[index].messages).includes("preserved task context")); }
      for (const index of [1, 3]) { assert.ok(JSON.stringify(requests[index].messages).length < 1000); assert.equal((requests[index].tools as unknown[] | undefined)?.length ?? 0, 0); }
      assert.deepEqual(canaryTransitions.map(item => item.request), [3, 4, 5]); assert.ok(canaryTransitions.every(item => item.incident.status === "OPEN"));
      assert.equal(new Set(canaryTransitions.map(item => item.incident.id)).size, 1); assert.deepEqual(canaryTransitions.map(item => item.incident.failures), [1, 2, 2]);
      assert.deepEqual(canaryTransitions.map(item => item.recovery.attempts), [1, 1, 2]); assert.equal(record.history.length, 2);
    });
    if (variant.startsWith("canary")) {
      assert.equal((requests[1].tools as unknown[] | undefined)?.length ?? 0, 0);
      assert.ok(!JSON.stringify(requests[1].messages).includes("synthetic fixture task"));
      assert.equal(record.canaryAttempts, variant === "canary" ? 1 : 2);
    }
    if (variant.startsWith("restart-")) {
      acceptance("AC07",variant === "restart-wait"?"restart-before":"restart-after",{level:"P",observer:"killed-and-relaunched-native-Pi-receiver",predicate:"restart retains deadline and one continuation",artifact:observerArtifact(`restart-${variant}`,{record,restartedProcess,requests,requestWallTimes,receiverStatuses})},()=>{
        assert.ok(restartedProcess);assert.equal(record.scopeId,restartedProcess.before.scopeId);assert.equal(record.deadlineAt,restartedProcess.before.deadlineAt);
        assert.equal(requests.length,2);assert.equal(record.attempts,1);assert.ok(requestWallTimes[1]>=restartedProcess.before.notBefore);
      });
      // Allow queued callbacks to drain before checking for duplicate dispatch.
      await delay(250);
      const ledger = new Store(join(root, "state"));
      try {
        for (const id of ["REC-009", "TK11"]) evidence(id, () => {
          assert.ok(restartedProcess); assert.notEqual(restartedProcess.beforePid, restartedProcess.afterPid);
          assert.equal(restartedProcess.signal, "SIGKILL");
          assert.equal(record.scopeId, restartedProcess.before.scopeId); assert.equal(record.sessionId, restartedProcess.before.sessionId);
          assert.deepEqual(record.history, restartedProcess.before.history); assert.equal(record.incidentId, restartedProcess.before.incidentId);
          assert.equal(record.deadlineAt, restartedProcess.before.deadlineAt); assert.ok(record.ownerEpoch > restartedProcess.before.ownerEpoch);
          assert.equal(record.status, "DONE"); assert.equal(record.attempts, 1); assert.equal(requests.length, 2);
          assert.ok(requestWallTimes[1] >= Math.max(restartedProcess.before.notBefore, restartedProcess.relaunchedAt));
          assert.equal(record.intentId, null); assert.equal(ledger.claims().length, 0);
          assert.equal(ledger.get<{identity:{pid:number}}>("owner-process", record.scopeId)!.identity.pid, child.pid);
          const intents = ledger.db.prepare("SELECT kind,status,native_id FROM intents").all();
          assert.equal(intents.length, 1); assert.equal(intents[0].kind, "continue"); assert.equal(intents[0].status, "settled");
          assert.ok(intents[0].native_id); assert.deepEqual(receiverStatuses.map(item => item.status), [429, 200]);
          const messages = requests[1].messages as Array<{role:string;content:unknown}>;
          assert.equal(messages.filter(message => message.role === "user" && JSON.stringify(message.content).includes("Perform the synthetic fixture task")).length, 1);
        });
      } finally { ledger.close(); }
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-observers"); mkdirSync(path, { recursive: true });
        writeFileSync(join(path, `${variant}.json`), JSON.stringify({ source: "Q2-loopback", restartedProcess, record,
          requests, requestWallTimes, receiverStatuses, events }, null, 2));
      }
    }
    if(variant === "missing-usage"){
      const observer=new Store(join(root,"state"));try{const facts=new UsageLedger(observer).facts(),last=facts.find(f=>f.outcome==="success")!;
        acceptance("AC10","missing-usage",{level:"A",observer:"successful-native-response-with-no-provider-usage",predicate:"SDK default zero is not evidence of free execution",artifact:observerArtifact("missing-usage",{usageSent:false,facts,events,receiverStatuses})},()=>{
          assert.equal(record.status,"DONE");assert.equal(last.tokens.input,null);assert.equal(last.cost.kind,"unknown");assert.equal(last.rawUsage!.buckets.input,0);assert.equal(last.coverage,"unknown");
        });
        acceptance("AC12","unknown",{level:"A",observer:"completed-real-request-with-no-metering-receipt",predicate:"missing consumption is not zero",artifact:observerArtifact("unknown-consumption",{last,requests})},()=>{assert.equal(last.tokens.input,null);assert.equal(last.cost.amount,null);assert.equal(last.cost.kind,"unknown");assert.equal(last.notSent,undefined);});
      }finally{observer.close();}
    }
    if(variant === "sdk-aggregate-retry"){
      const observer=new Store(join(root,"state"));try{const ledger=new UsageLedger(observer),facts=ledger.facts(),rows=ledger.query();
        acceptance("AC10","aggregate-retry",{level:"A",observer:"real-provider-SDK-retry-and-receiver",predicate:"one generation keeps two attempts and the final response's partial usage",artifact:observerArtifact("sdk-aggregate",{facts,rows,requests,receiverStatuses})},()=>{
          assert.equal(requests.length,2);assert.equal(facts.length,1);assert.equal(facts[0].attemptIds.length,2);assert.equal(facts[0].tokens.input,10);assert.equal(facts[0].tokens.output,10);
          assert.equal(facts[0].coverage,"final-response-only");assert.equal(rows[0].unknownCosts,1);assert.equal(rows[0].costs.USD.estimated,"0.00002");assert.equal(record.attempts,0);
        });
      }finally{observer.close();}
    }
    if(variant === "usage-task"){
      const observer=new Store(join(root,"state"));try{const ledger=new UsageLedger(observer),facts=ledger.facts(explicitUsageTask!),intents=observer.db.prepare("SELECT * FROM intents").all();
        acceptance("AC11","continue",{level:"A",observer:"native-quota-continuation-and-usage-links",predicate:"both generations remain under the original logical task",artifact:observerArtifact("task-continue",{facts,record})},()=>{assert.equal(facts.length,2);assert.equal(ledger.query()[0].task.id,explicitUsageTask);assert.equal(record.attempts,1);});
        send({id:"manual-model",type:"set_model",provider:providerId,modelId:"fixture-alternative"});await wait(()=>events.some(event=>event.id==="manual-model"),"manual model selection");
        send({id:"new-model-turn",type:"prompt",message:"Continue this same logical task using the selected model"});await wait(()=>requests.length===3&&events.filter(event=>event.type==="agent_settled").length>=3&&ledger.facts(explicitUsageTask!).length===3&&!ledger.facts(explicitUsageTask!).some(fact=>fact.source!=="native-SDK-generation"),"new model usage recorded");
        acceptance("AC11","manual-model-change",{level:"A",observer:"native-set-model-and-generation-links",predicate:"manual model change does not split logical task",artifact:observerArtifact("manual-model-usage",{facts:ledger.facts(explicitUsageTask!),requests})},()=>{
          assert.equal(requests[2].model,"fixture-alternative");assert.equal(ledger.facts(explicitUsageTask!).length,3);assert.equal(ledger.query().length,1);assert.equal(ledger.facts(explicitUsageTask!).filter(f=>f.model==="fixture-alternative").length,1);
        });
        const before=ledger.facts();
        for(const action of ["finish","accept"]){send({id:`task-${action}`,type:"prompt",message:action==="finish"?`/orch task finish ${explicitUsageTask}`:`/orch task finish ${explicitUsageTask} --accept`});await wait(()=>events.some(event=>event.id===`task-${action}`),`statistics ${action}`);
          const task=ledger.task(explicitUsageTask!);acceptance("AC11",action,{level:"A",observer:"native-user-command-and-unchanged-execution-ledger",predicate:`statistics ${action} does not send or clear execution`,artifact:observerArtifact(`task-${action}`,{task,requests})},()=>{assert.equal(task.status,action==="finish"?"finished":"accepted");assert.equal(task.resultSource,"user");assert.equal(requests.length,3);assert.deepEqual(observer.db.prepare("SELECT * FROM intents").all(),intents);});
        }
        acceptance("AC38","manual-stats-recovery",{level:"A",observer:"actual-user-task-begin-recovery-manual-model-change-and-acceptance",predicate:"one logical task includes failed recovery and later selected model",artifact:observerArtifact("combined-manual",{record,requests,facts:ledger.facts(explicitUsageTask!),task:ledger.task(explicitUsageTask!)})},()=>{assert.equal(requests.length,3);assert.equal(record.attempts,1);assert.equal(ledger.facts(explicitUsageTask!).length,3);assert.equal(ledger.task(explicitUsageTask!).status,"accepted");assert.equal(ledger.task(explicitUsageTask!).resultSource,"user");assert.equal(requests[2].model,"fixture-alternative");});
        send({id:"begin-correction",type:"prompt",message:"/orch task begin Corrected group"});await wait(()=>events.some(event=>event.id==="begin-correction"),"new statistics group");
        const next=ledger.query().find(row=>row.task.title==="Corrected group")!.task;
        send({id:"correct-usage",type:"prompt",message:`/orch reassign ${facts[1].generationId} ${next.id}`});await wait(()=>events.some(event=>event.id==="correct-usage"),"usage reassignment");
        acceptance("AC11","reassign",{level:"A",observer:"native-reassign-command-and-immutable-generation-facts",predicate:"only the task link changes",artifact:observerArtifact("task-reassign",{before,after:ledger.facts(),rows:ledger.query()})},()=>{assert.deepEqual(ledger.facts(),before);assert.equal(ledger.facts(next.id).length,1);assert.equal(ledger.facts(explicitUsageTask!).length,2);assert.equal(requests.length,3);assert.deepEqual(observer.db.prepare("SELECT * FROM intents").all(),intents);});
      }finally{observer.close();}
    }
    if(variant === "without-subagents")acceptance("AC35","no-subagents-recovery",{level:"A",observer:"actual-Pi-loading-private-package-without-subagents",predicate:"standalone recovery continues with bounded receiver calls",artifact:observerArtifact("no-subagents",{entry,record,requests})},()=>{assert.equal(existsSync(join(dirname(entry),"node_modules/pi-subagents")),false);assert.equal(record.status,"DONE");assert.equal(record.attempts,1);assert.equal(requests.length,2);});
    if(variant === "service-a")acceptance("AC36","Qwen-error-fixture",{level:"A",observer:"real-Pi-and-replayed-service-error-envelope",predicate:"Qwen-shaped errors are data for configured classification",artifact:observerArtifact("qwen-error-fixture",{sample,record,requests,receiverStatuses})},()=>{
      assert.equal(record.status,"DONE");assert.equal(record.attempts,1);assert.equal(record.history[0].category,sample!.expected);assert.equal(requests.length,2);
    });
    const continuationCase:Record<string,string[]>={"native-retry":["native-retry-success"],"write-before-limit":["tool-then-limit"],"auto-compaction":["auto-compaction"],"outer-recovery":["complete","canary-off"],"canary":["canary-no-code"],"canary-false-positive":["canary-false-positive"]};
    for(const acVariant of continuationCase[variant]??[])acceptance("AC06",acVariant,{level:"A",observer:"native-Pi-stream-tool-and-HTTP-receiver",predicate:`observed ${acVariant} retains one logical continuation`,artifact:observerArtifact(`continuation-${acVariant}`,{record,events,requests,receiverStatuses})},()=>{
      assert.equal(record.status,"DONE");assert.equal(record.intentId,null);
      if(variant === "native-retry"){assert.equal(record.attempts,0);assert.equal(requests.length,2);}
      if(variant === "write-before-limit"){assert.equal(readFileSync(join(cwd,"proof.txt"),"utf8"),"once\n");assert.equal(events.filter(event=>event.type==="tool_execution_end"&&event.toolName==="write").length,1);}
      if(variant === "outer-recovery"){assert.equal(record.attempts,1);assert.equal(record.canaryAttempts??0,0);assert.equal(requests.length,2);}
      if(variant.startsWith("canary")){assert.equal((requests[1].tools as unknown[]|undefined)?.length??0,0);assert.ok(record.attempts>0);}
      if(variant === "auto-compaction")assert.ok(events.some(event=>event.type==="compaction_end"&&!event.errorMessage));
    });
    if (variant === "current-session") acceptance("AC03", "current-session", { level:"A", observer:"native-Pi-RPC-and-HTTP-receiver", predicate:"current Pi model without explicit route",
      artifact:observerArtifact("current-session", {record,requests,receiverStatuses,events}) }, () => {
      assert.equal(record.status,"DONE");assert.equal(record.attempts,1);assert.ok(record.routeId.startsWith("current-"));
      assert.deepEqual(receiverStatuses.map(item=>item.status),[429,200]);assert.equal(requests.length,2);
      assert.ok(requests.every(request=>request.model===modelId));assert.deepEqual(config.routes,{});
      assert.equal(JSON.stringify(record).includes("fixture-not-a-real-credential"),false);
    });
    if(variant === "cache-usage"){
      const observer=new Store(join(root,"state"));try{const facts=new UsageLedger(observer).facts(),last=facts.find(f=>f.outcome==="success")!;
        acceptance("AC10","cache-in-input",{level:"A",observer:"real-Pi-SDK-and-fixed-receiver-cache-usage",predicate:"10 prompt tokens includes 6 cached tokens; no double counting",artifact:observerArtifact("cache-usage",{facts,events,receiverStatuses})},()=>{
          assert.equal(last.tokens.input,4);assert.equal(last.tokens.cacheRead,6);assert.equal(last.tokens.output,10);assert.equal(last.tokens.cacheWrite,0);
          assert.equal(last.rawUsage!.totalTokens,20);assert.equal(last.tokens.input!+last.tokens.cacheRead!+last.tokens.output!,20);
        });
      }finally{observer.close();}
    }
    if(variant === "current-session"){
      const observer=new Store(join(root,"state"));try{
        const facts=new UsageLedger(observer).facts(),last=facts.find(f=>f.outcome==="success")!;
        acceptance("AC10","parent",{level:"A",observer:"native-SDK-message-and-HTTP-receiver",predicate:"receiver emitted 10 input and 10 output tokens",artifact:observerArtifact("parent-usage",{facts,events,receiverStatuses})},()=>{
          assert.equal(facts.length,2);assert.equal(last.tokens.input,10);assert.equal(last.tokens.output,10);assert.equal(last.tokens.cacheRead,0);assert.equal(last.tokens.cacheWrite,0);
          assert.equal(facts.find(f=>f.outcome==="failure")!.cost.kind,"unknown");assert.equal(last.provider,providerId);assert.equal(last.model,modelId);
        });
      }finally{observer.close();}
    }
    const messages = requests[variant === "auto-compaction" ? 1 : requests.length - 1].messages as Array<{ role: string; content: unknown }>;
    if (variant === "compaction-history") {
      assert.ok(JSON.stringify(messages).includes("failureCategories")); assert.ok(JSON.stringify(messages).includes("frequency_limit"));
    } else assert.ok(JSON.stringify(messages).includes("synthetic fixture task"));
    if (variant === "write-before-limit") {
      send({id:"long-task-status",type:"prompt",message:"/throttle status"});await wait(()=>events.some(event=>event.id==="long-task-status"),"long task terminal UI");
      const ui=events.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(String(event.message))];}catch{return[];}}).filter(value=>value.recovery).at(-1);
      const ledger=new Store(join(root,"state"));try{
        for(const id of ["REC-001","TK09"])evidence(id,()=>{
          assert.equal(readFileSync(join(cwd,"proof.txt"),"utf8"),"once\n");assert.equal(events.filter(event=>event.type==="tool_execution_start"&&event.toolName==="write").length,1);
          assert.equal(events.filter(event=>event.type==="tool_execution_end"&&event.toolName==="write"&&event.isError!==true).length,1);
          assert.deepEqual(receiverStatuses.map(item=>item.status),[200,429,200]);assert.equal(requests.length,3);
          assert.ok(JSON.stringify(messages).length>20000);assert.ok(messages.some(message=>message.role==="tool"));
          assert.equal(messages.filter(message=>message.role==="user"&&JSON.stringify(message.content).includes("Perform the synthetic fixture task")).length,1);
          assert.equal(record.status,"DONE");assert.equal(record.attempts,1);assert.equal(record.history.length,1);assert.equal(ui.recovery.sessionId,record.sessionId);assert.equal(ui.recovery.status,"DONE");
          assert.equal(ledger.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue' AND status='settled'").get()!.n,1);assert.equal(ledger.claims().length,0);
        });
      }finally{ledger.close();}
      if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"recovery-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"long-task-after-write.json"),JSON.stringify({record,ui,requests,receiverStatuses,events,effect:readFileSync(join(cwd,"proof.txt"),"utf8")},null,2));}
    }
  });
}
