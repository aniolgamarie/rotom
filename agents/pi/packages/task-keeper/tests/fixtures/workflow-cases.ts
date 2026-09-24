import {nativeDispatchCut} from "./native-dispatch-cut.ts";
import {outcome,type ExecutionFacts,type TaskSpec} from "../../src/contracts/task.ts";
import {runVerification} from "../../src/verification/runner.ts";
import {sourceSnapshot} from "../../src/workspace/worktree.ts";
import {modelBindingDigest} from "../../src/adapters/capabilities.ts";
import {comparisonPolicyDigest,configurationPolicyDigest} from "../../src/config.ts";
import {verificationInputs} from "../../src/verification/inputs.ts";
import {digest} from "../../src/contracts/primitives.ts";
import { UsageLedger, sdkUsage } from "../../src/usage/ledger.ts";
import { resumeSnapshotCut } from "./resume-snapshot-cut.ts";
import { contendWithCandidateVerifier, holdCandidateVerifier, verifierWorkspaceCut } from "./sch010-workspace-freeze.ts";
import { sharedWriteResources } from "../../src/workspace/shared-resources.ts";
import { originalProcessStopped, processIdentity } from "../../src/adapters/process-identity.ts";
import type { VerificationResult } from "../../src/verification/runner.ts";
import { test, assert, evidence, matrixCase, acceptance, observerArtifact } from "../recorded-test.ts";
import { fork, type ChildProcess, spawn, execFileSync } from "node:child_process";
import { createServer, type ServerResponse } from "node:http";
import { once } from "node:events";
import { mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, readlinkSync, unlinkSync, cpSync, symlinkSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { Artifacts } from "../../src/store/artifacts.ts";
import { Store } from "../../src/store/database.ts";
import type { ManagedJob } from "../../src/orchestration/service.ts";
import { strippedReviewInput } from "./review-input-cut.ts";
import { contextWithoutAbort } from "./context-abort-cut.ts";
import { verifierCompletionCut } from "./verifier-completion-cut.ts";
import { configured } from "./config.ts";
import { isolatedDirectory, listenLoopback } from "../helpers.ts";

const reportedUsage=new WeakMap<ServerResponse,number>();
function answer(res: ServerResponse, tools: Array<{ name: string; args: unknown }> = [], inputTokens?: number, replyText?: string) {
  inputTokens??=reportedUsage.get(res);
  res.writeHead(200, { "content-type": "text/event-stream" });
  const delta = tools.length ? { role: "assistant", tool_calls: tools.map((tool, index) => ({ index, id: `call-${index}`, type: "function",
    function: { name: tool.name, arguments: JSON.stringify(tool.args) } })) } : { role: "assistant", content: replyText ?? "Fixture complete; acceptance is determined by parent." };
  for (const choice of [{ index: 0, delta, finish_reason: null }, { index: 0, delta: {}, finish_reason: tools.length ? "tool_calls" : "stop" }])
    res.write(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", created: 1, model: "fixture-model", choices: [choice], ...(inputTokens === undefined ? {} : { usage: { prompt_tokens: inputTokens, completion_tokens: 10, total_tokens: inputTokens + 10 } }) })}\n\n`);
  res.end("data: [DONE]\n\n");
}

const coverageIds: Record<string, string> = {"opinion-stale-checks":"","opinion-deadline":"","opinion-missing":"", "opinion-readonly":"", "opinion-unsupported":"","deadline-verifier":"","history-model":"","auto-model":"", "auto-model-off":"", "auto-model-repair":"","opinion-different-reviewer":"","opinion-off":"","schedule-restart-future":"", "schedule-missed":"","child-usage":"","scheduled":"","opinion-unresolved":"", "opinion-zero":"", "opinion-revise":"", "second-opinion":"","snapshot-pause-revoke-first": "", "snapshot-pause-await-first": "", "snapshot-stop-revoke-first": "", "snapshot-stop-await-first": "", "snapshot-dispose-revoke-first": "", "snapshot-dispose-await-first": "",  "verifier-first": "SCH-010 TK06", "replan-repair": "WFL-012", "replan-zero": "WFL-012", "proposal-valid": "EVD-008 EVD-009 RTB-019 T60 T62 T63 T64 T65 T70 T85", "proposal-stale": "EVD-007 T59", "proposal-tool": "EVD-008", "shared-directory": "SCH-009 TK05", "shared-directory-drift": "SCH-009", "writers-disabled-command": "CFG-004", "writers-disabled-tool": "CFG-004", "fallback-budget-exhausted": "RTB-010 T28", "cancel-after-edit": "WFL-011", "workspace-failure": "WFL-003 T43", "spawn-failure": "EXE-005", "baseline-environment-failure": "T79", "invalid-plan": "SCH-004 TK02", "silent-build": "EXE-013 T16", "interrupted-zero": "EXE-006 T02", "scope-forged-input": "SCH-002 EXE-001 T48", "candidate-edit": "T45", "check-threshold-change": "T46", "premature-critic": "", "budget-local-verification": "RTB-012", "terminal-resume": "CFG-012", "worker-compaction-failure": "", "worker-compaction-quota": "REC-010", inspect: "WFL-002", fix: "WFL-005 WFL-012 EVD-012 EXE-007", repair: "WFL-012 EVD-003 EVD-012", "step-cap": "WFL-007 T72", "zero-tests": "WFL-004 EVD-010 T44", "details-only-error": "T10", "summary-hides-failure": "EVD-004 T11 T53 T57", "packet-overflow": "EVD-005 T56", "packet-overflow-no-abort": "EVD-005 T56", "all-skipped": "WFL-004 EVD-010 T44", "unknown-tests": "WFL-004 EVD-010 T44", "unread-review": "WFL-009", "worker-claim": "T55", "premature-review": "WFL-009 T03", "stripped-review-input": "WFL-009", "forged-artifact": "EVD-006 T54", "mutating-check": "WFL-005", cancel: "EXE-011", "quota-recovery": "REC-018", fallback: "RTB-005", "same-model-repair": "RTB-015", critique: "RTB-016", "critic-reserve": "RTB-018 T82", "critique-revise": "RTB-015", "multi-job": "REC-022 SCH-013", "recovered-tool-error": "EVD-003 EVD-004 EXE-012", "tool-entry": "CFG-001 CFG-013 SCH-001", "combined-recipes": "RTB-015 EVD-003", "check-input-change": "WFL-005 CFG-007", "check-approval": "WFL-005 CFG-007", "build-repair": "WFL-006 WFL-012", "environment-failure": "WFL-006", "review-reuse": "WFL-010", "optional-failure": "EVD-011", "optional-disallowed": "T13", "binding-approval": "CFG-007", "fallback-skip-network": "RTB-001", "fallback-skip-telemetry": "RTB-001", "fallback-skip-context": "RTB-001 T27 T78", "fallback-skip-thinking": "RTB-002", "network-recovery": "REC-005", "network-exhausted": "REC-005", "scope-job-cap": "SCH-002", "scope-fork-cap": "SCH-001 T30", "scope-semantic-cap": "SCH-001 T30", "artifact-loss": "EVD-013 T47", "runtime-upgrade": "EXE-002 WFL-005", "combined-features": "", "combined-tool-recovery": "", "model-control-race": "CFG-001 REC-019", "cancel-verifier-first": "EXE-011", "cancel-verifier-late": "EXE-011" };
export const WORKFLOW_VARIANTS = ["opinion-request-timeout","opinion-one","scheduled-explicit","opinion-disagreement-budget","schedule-floor","opinion-restart","opinion-budget","schedule-window","opinion-quota","opinion-permanent","opinion-cancel","schedule-resources","schedule-no-window","schedule-expired","cut-start-C0", "cut-start-C1", "cut-start-C2", "cut-start-C3", "cut-start-C4", "cut-start-C5", "cut-verify-C0", "cut-verify-C1", "cut-verify-C2", "cut-verify-C3", "cut-verify-C4", "cut-verify-C5","opinion-stale-checks","opinion-deadline","opinion-missing", "opinion-readonly", "opinion-unsupported","deadline-verifier","history-model","auto-model", "auto-model-off", "auto-model-repair","opinion-different-reviewer","opinion-off","schedule-restart-future", "schedule-missed","child-usage","scheduled","opinion-unresolved", "opinion-zero", "opinion-revise", "second-opinion","snapshot-pause-revoke-first", "snapshot-pause-await-first", "snapshot-stop-revoke-first", "snapshot-stop-await-first", "snapshot-dispose-revoke-first", "snapshot-dispose-await-first", "verifier-first", "replan-repair", "replan-zero","proposal-valid", "proposal-stale", "proposal-tool","shared-directory", "shared-directory-drift","writers-disabled-command", "writers-disabled-tool","fallback-budget-exhausted", "cancel-after-edit", "workspace-failure", "spawn-failure", "baseline-environment-failure", "invalid-plan", "silent-build", "interrupted-zero", "scope-forged-input", "candidate-edit", "check-threshold-change", "premature-critic", "budget-local-verification", "terminal-resume", "worker-compaction-quota", "worker-compaction-failure", "inspect", "fix", "repair", "worker-claim", "step-cap", "zero-tests", "details-only-error", "summary-hides-failure", "packet-overflow", "packet-overflow-no-abort", "all-skipped", "unknown-tests", "unread-review", "premature-review", "stripped-review-input", "forged-artifact", "mutating-check", "cancel", "quota-recovery", "fallback", "same-model-repair", "critique", "critic-reserve", "critique-revise", "multi-job", "recovered-tool-error", "tool-entry", "combined-recipes", "check-input-change", "check-approval", "build-repair", "environment-failure", "review-reuse", "optional-failure", "optional-disallowed", "binding-approval", "fallback-skip-network", "fallback-skip-telemetry", "fallback-skip-context", "fallback-skip-thinking", "network-recovery", "network-exhausted", "scope-job-cap", "scope-fork-cap", "scope-semantic-cap", "artifact-loss", "runtime-upgrade", "combined-features", "combined-tool-recovery", "model-control-race", "cancel-verifier-first", "cancel-verifier-late"] as const;
export type WorkflowVariant = typeof WORKFLOW_VARIANTS[number];
export function registerWorkflowCases(variants: readonly WorkflowVariant[]) {
for (const variant of variants) test(`[${variant.startsWith("cut-") ? "A P E" : variant === "opinion-stale-checks" ? "P S E" : variant === "child-usage" ? "A S E" : variant.startsWith("snapshot-") ? "A E" : variant === "verifier-first" ? "P" : (variant.startsWith("writers-disabled-") || variant.startsWith("shared-directory") || variant.startsWith("proposal-") || variant === "scope-forged-input") ? "A E" : ["fallback-budget-exhausted", "cancel-after-edit", "workspace-failure", "spawn-failure", "baseline-environment-failure", "invalid-plan", "silent-build", "interrupted-zero"].includes(variant) ? "A P E" : ["fix", "repair", "check-threshold-change", "candidate-edit"].includes(variant) ? "P E" : (variant === "budget-local-verification" || variant.startsWith("fallback-skip") || variant.startsWith("cancel-verifier") || variant.startsWith("packet-overflow")) ? "A P E" : ["terminal-resume", "fallback", "worker-compaction-quota", "summary-hides-failure", "details-only-error", "forged-artifact", "premature-review", "stripped-review-input"].includes(variant) ? "A E" : variant === "artifact-loss" ? "P E" : variant === "runtime-upgrade" ? "A P E" : "E"} ${coverageIds[variant]??""}] ${variant} ${variant.startsWith("snapshot-") ? "preserves control after actual snapshot completion" : variant === "verifier-first" ? "freezes candidate bytes until real verifier release" : "reaches independently verified receipt and preserves user tree"}`, { timeout: variant === "schedule-window"?150000:90000 }, async (t) => {
  const usesShared = variant.startsWith("shared-directory") || variant.startsWith("proposal-");
  let proposalModelJob: string | null = null; const proposalWitness: unknown[] = [];
  const workflow = variant === "inspect" ? "inspect" : "fix";
  const toolEntry = variant.startsWith("snapshot-") || variant === "writers-disabled-tool" || variant === "tool-entry" || (variant.startsWith("scope-") && variant !== "scope-fork-cap") || variant === "combined-tool-recovery" || variant === "model-control-race";
  const diagnosisInputs: unknown[] = [], diagnosisWriterInputs: unknown[] = []; let diagnosisRequests = 0;
  const parentToolResults: string[] = []; let acceptReviewRetry = false;
  let statusJobId: string | null = null;let scheduleStatusShown=false;
  const root = isolatedDirectory(t), agentDir = join(root, "agent"), cwd = join(root, "workspace"), state = join(root, "state");
  mkdirSync(agentDir); mkdirSync(cwd);
  if(variant === "workspace-failure"){mkdirSync(state,{mode:0o700});writeFileSync(join(state,"worktrees"),"preserve obstruction");}
  const git = (...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8" });
  git("init", "-q"); git("config", "user.email", "fixture@example.invalid"); git("config", "user.name", "Fixture");
  writeFileSync(join(cwd, "answer.json"), '{"answer":1}\n');
  if (variant.startsWith("check-")) writeFileSync(join(cwd, "checks.json"), '{"expected":2}\n');
  git("add", "."); git("commit", "-qm", "fixture");
  writeFileSync(join(cwd, "user-edit.txt"), "preserved\n");
  if (variant === "writers-disabled-command") { mkdirSync(join(cwd, ".pi")); writeFileSync(join(cwd, ".pi/task-keeper.json"), JSON.stringify({ limits: { writersPerJob: 0 } })); }
  const before = git("status", "--porcelain=v1"), refs = git("show-ref");
  const sourcePkg = fileURLToPath(new URL("../..", import.meta.url));
  const pkg = variant.startsWith("cut-") ? nativeDispatchCut(sourcePkg,root,variant.split("-")[1] as "start"|"verify",variant.split("-")[2]) : variant.startsWith("snapshot-") ? resumeSnapshotCut(sourcePkg, root) : variant === "verifier-first" && process.env.TASK_KEEPER_SCH010_CUT ? verifierWorkspaceCut(sourcePkg, root) : variant === "stripped-review-input" ? strippedReviewInput(sourcePkg, root) : variant === "packet-overflow-no-abort" ? contextWithoutAbort(sourcePkg, root) : variant === "cancel-verifier-late" ? verifierCompletionCut(sourcePkg, root) : variant === "runtime-upgrade" ? join(root, "runtime-package") : sourcePkg;
  if (variant === "runtime-upgrade") {
    mkdirSync(pkg);
    for (const file of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(sourcePkg, file), join(pkg, file), { recursive: true });
    symlinkSync(join(sourcePkg, "node_modules"), join(pkg, "node_modules"));
  }
  const sharedRoot = join(root, "shared-build"), sharedAlias = join(root, "shared-alias");
  const sharedObservations: unknown[] = []; let sharedHolder: ChildProcess | undefined, sharedIntent: string | undefined, sharedReleased = false, sharedRetargeted = false;
  if (usesShared) { mkdirSync(sharedRoot); symlinkSync(sharedRoot, sharedAlias); }
  if (usesShared && variant !== "shared-directory-drift") {
    sharedHolder = fork(join(sourcePkg, "tests/fixtures/resource-worker.ts"), [state, "external", "declared", sharedRoot],
      { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "ignore", "ipc"] });
    t.after(async () => { if (sharedHolder!.exitCode === null && sharedHolder!.signalCode === null) { const exit = once(sharedHolder!, "exit"); sharedHolder!.kill("SIGKILL"); await exit; } });
    const [ready] = await once(sharedHolder, "message", { signal: AbortSignal.timeout(10000) }); assert.equal(ready.type, "ready");
    const acquired = once(sharedHolder, "message", { signal: AbortSignal.timeout(10000) }); sharedHolder.send("go"); const [held] = await acquired;
    assert.equal(held.acquired, true); sharedIntent = held.intent;
  }
  const requestedModels: string[] = []; const parentInputs: unknown[] = [], reviewInputs: unknown[] = []; let summaryRequests = 0, foreignArtifact = "";
  let opinionStartedAt=0;let opinionHeld=false,opinionClosed=false,opinionRejected=false,opinionControlSent=false;let opinionFloor=0;let windowEnd=0,windowHeld=false;let scheduleFloor=0,observedFloorQueue=false;
  let heldParentResponse: ServerResponse | null = null;
  let heldCandidateResponse: ServerResponse | null = null, candidateConnectionClosed = false;
  const backupHandoffs: Array<{ job: ManagedJob; implementationStatus: string; incident: {id: string; status: string}; used: number; reserved: number }> = [];
  let compactionNotBefore = 0; const reviewCooldowns: Array<{at: number; incident: {status: string; notBefore: number} | null}> = [];
  const budgetLimitCounts={primary:0,backup:0};
  let requests = 0, parentRequests = 0, reviewRequests = 0, writes = 0, criticRequests = 0, independentCompleted = false;
  const server = createServer((req, res) => {
    if(variant === "child-usage" || variant === "opinion-different-reviewer")reportedUsage.set(res,100);
    if(variant === "history-model")reportedUsage.set(res,10000);
    let body = ""; req.on("data", (data) => { body += data; }); req.on("end", () => {
      requests++;
      const input = JSON.parse(body); requestedModels.push(input.model);
      if (usesShared && input.tools?.some((tool: {function?: {name?: string}}) => tool.function?.name === "tk_write")) {
        const observer = new Store(state); try { sharedObservations.push({ kind: "writer-request", claims: observer.claims().filter(claim => String(claim.resource_id).startsWith("shared-directory-")).map(claim => ({ ...claim, intent: observer.intent(String(claim.intent_id)) })) }); } finally { observer.close(); }
      }
      if (variant.startsWith("worker-compaction-") && !input.tools?.length) {
        summaryRequests++;
        if (variant === "worker-compaction-quota") {
          compactionNotBefore = Date.now() + 5000; res.writeHead(429, { "content-type": "application/json", "retry-after": "5" });
          res.end('{"error":{"message":"fixture_compaction_failure: quota limited","code":"rate_limit"}}');
        } else {
          res.writeHead(400, { "content-type": "application/json" }); res.end('{"error":{"message":"fixture_compaction_failure: context window exceeded","code":"context_limit"}}');
        }
        return;
      }
      if (variant === "summary-hides-failure" && !(input.tools?.length)) { summaryRequests++; answer(res); return; }
      if (input.tools?.some((tool: { function?: { name?: string } }) => tool.function?.name === "kernel_task")) {
        parentRequests++; parentInputs.push(input.messages);
        if (variant === "summary-hides-failure") { answer(res); return; }
        if (variant === "model-control-race" && parentRequests === 2) { heldParentResponse = res; return; }
        if (variant === "combined-tool-recovery" && parentRequests === 2) {
          res.writeHead(429, { "content-type": "application/json", "retry-after": "0" }); res.end('{"error":{"message":"fixture parent limited","code":"rate_limit"}}'); return;
        }
        if (variant === "proposal-tool" && proposalModelJob) {
          const results = input.messages.filter((message: {role: string}) => message.role === "tool");
          parentToolResults.push(...results.map((message: {content: unknown}) => JSON.stringify(message.content)));
          const parsed = results.flatMap((message: {content: unknown}) => {
            try { const value = typeof message.content === "string" ? message.content : (message.content as Array<{text?: string}>).map(item => item.text ?? "").join(""); return [JSON.parse(value)]; } catch { return []; }
          });
          if (parsed.some((value: any) => value.contract)) answer(res);
          else { const view = parsed.find((value: any) => value.packet);
            if (view) answer(res, [{ name: "kernel_task", args: { action: "propose", jobId: proposalModelJob,
              proposal: { packetId: view.packet.id, action: "verify", target: "baseline:build", reason: "Use the frozen baseline", evidenceIds: [] } } }]);
            else answer(res, [{ name: "kernel_task", args: { action: "decisions", jobId: proposalModelJob } }]);
          }
          return;
        }
        if (input.messages.some((message: { role: string }) => message.role === "tool")) {
          parentToolResults.push(...input.messages.filter((message: { role: string }) => message.role === "tool").map((message: { content: unknown }) => JSON.stringify(message.content)));
          answer(res);
        } else if (statusJobId) answer(res, [{ name: "kernel_task", args: { action: variant === "terminal-resume" ? "resume" : "status", jobId: statusJobId } }]);
        else if(variant === "scope-forged-input") answer(res,[
          {name:"kernel_task",args:{action:"fix",goal:"Set answer to 2",workScope:"forged-scope"}},
          {name:"kernel_task",args:{action:"fix",goal:"Set answer to 2",context:"fork"}},
          {name:"kernel_task",args:{action:"fix",goal:"Set answer to 2",background:true}},
          {name:"kernel_task",args:{action:"fix",goal:"Set answer to 2",automatic:true}},
          {name:"kernel_task",args:{action:"fix",goal:"Set answer to 2",secondOpinion:true}},
        ]);
        else answer(res, [
          { name: "kernel_task", args: { action: "fix", goal: "Set answer to 2" } },
          ...(variant.startsWith("scope-") && !["scope-fork-cap", "scope-forged-input"].includes(variant) ? [{ name: "kernel_task", args: { action: "fix", goal: "Start a replacement task in the same scope" } }] : []),
        ]);
        return;
      }
      if(variant === "fallback-budget-exhausted"){
        const primary=input.model==="fixture-model";budgetLimitCounts[primary?"primary":"backup"]++;
        res.writeHead(429,{"content-type":"application/json","retry-after":primary?"120":"0"});
        res.end(JSON.stringify({error:{code:"rate_limit",message:primary?"primary remains unavailable":"bounded backup also limited"}}));return;
      }
      if (((variant === "quota-recovery" || variant === "network-recovery") && requests === 1) || variant === "network-exhausted" || (variant.startsWith("fallback") && input.model === "fixture-model" && requests <= 2) || (variant === "multi-job" && input.model === "fixture-model" && !independentCompleted)) {
        res.writeHead(variant.startsWith("network-") ? 503 : 429, { "content-type": "application/json", "retry-after": "1" }); res.end('{"error":{"message":"fixture limited","code":"rate_limit"}}'); return;
      }
      if(variant === "schedule-floor" && requests===1){scheduleFloor=Date.now()+12000;res.writeHead(429,{"content-type":"application/json","retry-after":"12"});res.end('{"error":{"message":"shared account quota","code":"rate_limit"}}');return;}
      if(variant === "schedule-floor" && requests>1)assert.ok(Date.now()>=scheduleFloor);
      const text = JSON.stringify(input.messages);
      if(variant === "cut-start-C2" && requests===2){writeFileSync(join(root,"native-cut.json"),JSON.stringify({family:"start",point:"C2",at:Date.now(),receiverCount:requests}));return;}
      if(variant === "opinion-unsupported" && !text.includes("TASK_KEEPER_DESCRIPTOR")){answer(res,[],10,"Already streamed ordinary answer");return;}
      const review = text.includes("TASK_KEEPER_REVIEW");
      const hasTool = input.messages.some((message: { role: string }) => message.role === "tool");
      if (text.includes("TASK_KEEPER_REPLAN_DIAGNOSIS")) {
        diagnosisRequests++; diagnosisInputs.push(input.messages);
        const artifacts = [...new Set(text.match(/artifact-[a-f0-9]+/g) ?? [])];
        if (!hasTool) answer(res, [{ name: "tk_read", args: { path: "answer.json" } }, ...artifacts.map(id => ({name:"tk_read",args:{path:`artifact:${id}`}}))]);
        else answer(res, [], undefined, "DIAGNOSIS_FIXTURE_MARKER: the current answer is wrong; preserve required checks and repair the implementation.");
        return;
      }
      if (variant.startsWith("replan-") && !review) {
        const observer = new Store(state); let diagnostic: string | undefined;
        try { diagnostic = observer.list<ManagedJob>("managed-jobs")[0]?.value.outputs["replan:diagnose:1"]; } finally { observer.close(); }
        const write = () => answer(res, [{ name: "tk_write", args: { path: "answer.json", content: writes <= (variant === "replan-repair" ? 2 : 1) ? '{"answer":0}\n' : '{"answer":2}\n' } }]);
        if (!hasTool) { writes++; if (diagnostic) answer(res, [{name:"tk_read",args:{path:`artifact:${diagnostic}`}}]); else write(); }
        else if (diagnostic && !text.includes('"name":"tk_write"')) { diagnosisWriterInputs.push(input.messages); write(); }
        else answer(res);
        return;
      }
      if(variant === "opinion-revise" && !review && text.includes("Exchange: 1/")){
        answer(res,[],undefined,"EVIDENCE_REBUTTAL second-view: the supplied build and focused-test evidence already validates this unchanged candidate. Retain the current source.");return;
      }
      if (review) {
        reviewRequests++; reviewInputs.push(input.messages);
        if(variant === "opinion-restart" && text.includes("TASK_KEEPER_SECOND_OPINION")){opinionHeld=true;opinionStartedAt=Date.now();res.on("close",()=>{opinionClosed=true;});return;}

        if(["opinion-quota","opinion-permanent"].includes(variant) && text.includes("TASK_KEEPER_SECOND_OPINION") && !opinionRejected){
          opinionRejected=true;opinionFloor=Date.now()+2000;
          res.writeHead(variant === "opinion-quota"?429:401,{"content-type":"application/json",...(variant === "opinion-quota"?{"retry-after":"2"}:{})});res.end(JSON.stringify({error:{message:variant === "opinion-quota"?"B temporary quota":"B credential rejected",code:variant === "opinion-quota"?"rate_limit":"invalid_api_key"}}));return;
        }
        if(variant === "opinion-quota" && opinionRejected)assert.ok(Date.now()>=opinionFloor);

        if(["opinion-deadline","opinion-cancel","opinion-request-timeout"].includes(variant) && text.includes("TASK_KEEPER_SECOND_OPINION")){opinionHeld=true;opinionStartedAt=Date.now();res.on("close",()=>{opinionClosed=true;});res.writeHead(200,{"content-type":"text/event-stream"});res.flushHeaders();res.write('data: {"choices":[{"index":0,"delta":{"content":"Partial B opinion"},"finish_reason":null}]}\n\n');return;}
        if (variant === "fallback" && backupHandoffs.length === 0) {
          const observer = new Store(state);
          try {
            const current = observer.list<ManagedJob>("managed-jobs").find(item => item.value.workflow === "fix")!.value;
            const plan = observer.get<{steps:Array<{id:string;status:string}>}>("jobs", current.id)!;
            const incident = observer.get<{id:string;status:string}>("incidents", "pool")!, budget = observer.bucket(`incident-${current.recovery!.incidentId}`)!;
            backupHandoffs.push({ job: current, implementationStatus: plan.steps.find(step => step.id === "implement")!.status,
              incident, used: Number(budget.used), reserved: Number(budget.reserved) });
          } finally { observer.close(); }
        }

        if (variant === "worker-compaction-quota") {
          const observer = new Store(state); try { reviewCooldowns.push({ at: Date.now(), incident: observer.get("incidents", "pool") }); } finally { observer.close(); }
        }
        let secondRevision=false;
        if(["opinion-revise","opinion-zero","opinion-one","opinion-unresolved","opinion-disagreement-budget","critique-revise","combined-recipes"].includes(variant) && text.includes("TASK_KEEPER_SECOND_OPINION")){
          const observer=new Store(state);try{secondRevision=["opinion-zero","opinion-one","opinion-unresolved","opinion-disagreement-budget"].includes(variant) || (observer.list<ManagedJob>("managed-jobs")[0]?.value.opinion?.exchanges??0)===0;}finally{observer.close();}
        }
        const critic = text.includes("Purpose: diagnostic") || text.includes("TASK_KEEPER_SECOND_OPINION"); if (critic) criticRequests++;
        const snapshot = /Snapshot: (tree-[a-f0-9]+)/.exec(text)?.[1];
        const artifacts = [...new Set(text.match(/artifact-[a-f0-9]+/g) ?? [])];
        if (!hasTool && ((variant === "premature-review" && !acceptReviewRetry) || (variant === "premature-critic" && critic))) {
          answer(res, [{ name: "tk_read", args: { path: "answer.json" } }, ...artifacts.map(id => ({ name: "tk_read", args: { path: `artifact:${id}` } })),
            { name: "structured_output", args: { value: { verdict: "pass", snapshot, summary: "Verdict generated before seeing tool results", scopeComplete: true,
              findings: [], evidence: [{ path: "answer.json", startLine: 1, endLine: 1 }], unverified: [] } } }]);
        } else if (!hasTool && variant === "forged-artifact") {
          const observer = new Store(state);
          try { foreignArtifact = new Artifacts(observer).pin("foreign-job", "foreign-tree", "FOREIGN_PRIVATE_SENTINEL", "verifier").id; } finally { observer.close(); }
          answer(res, [{ name: "tk_read", args: { path: `artifact:${foreignArtifact}` } }]);
        } else if (!hasTool && variant !== "unread-review") answer(res, [{ name: "tk_read", args: { path: "answer.json" } }, ...artifacts.map((id) => ({ name: "tk_read", args: { path: `artifact:${id}` } }))]);
        else if (!text.includes('"name":"structured_output"')) answer(res, [{ name: "structured_output", args: { value: {
          verdict: secondRevision?"fail":"pass", snapshot, summary: variant === "opinion-revise" && !secondRevision ? "Withdraw second-view after reading the A rebuttal and current verifier evidence" : "Observed expected source and complete supplied evidence", scopeComplete: true, findings: secondRevision?[{id:"second-view",severity:"high",message:"Reconsider the implementation evidence",actionable:true,evidenceIndices:[0]}]: (variant === "critique-revise" || variant === "combined-recipes") && critic ? [{ id: "finding", severity: "medium", message: "Add a supporting implementation note", actionable: true, evidenceIndices: [0] }] : [],
          resolvedFailures: acceptReviewRetry ? [...new Set(text.match(/step-[a-f0-9]+:review-contract/g) ?? [])] : variant === "recovered-tool-error" ? [...new Set(text.match(/child-[a-f0-9-]+:call-\d+/g) ?? [])] : [],
          evidence: [{ path: "answer.json", startLine: 1, endLine: 1 }], unverified: [],
        } } }]);
        else answer(res);
      } else if (!hasTool) {
        if(variant === "schedule-window" && !windowHeld){windowHeld=true;writes++;const tools=[{name:"tk_write",args:{path:"answer.json",content:'{"answer":2}\n'}}];setTimeout(()=>answer(res,tools),Math.max(1,windowEnd-Date.now()+100));return;}
        writes++;
        const tools: Array<{ name: string; args: { path: string; content?: string } }> = input.tools?.some((tool: { function?: { name?: string } }) => tool.function?.name === "tk_write") ? [{ name: "tk_write", args: { path: "answer.json", content: (variant === "check-threshold-change" || variant === "repair" || variant === "auto-model-repair" || variant === "step-cap" || variant === "same-model-repair" || variant === "combined-recipes") && writes === 1 ? '{"answer":0}\n' : '{"answer":2}\n' } }]
          : [{ name: "tk_read", args: { path: "answer.json" } }];
        if (variant === "cancel" || (variant === "binding-approval" && writes === 1)) setTimeout(() => { if (!res.destroyed) answer(res, tools); }, 1500).unref(); else {
          if (variant === "worker-claim") tools[0].args = { path: "claimed-verification.json", content: '{"tests":99,"passed":99,"failed":0,"skipped":0,"claim":"all checks passed"}\n' };
          if (variant === "build-repair" && writes === 1) tools[0].args.content = '{"broken":';
          if (variant.startsWith("check-")) tools.push({ name: "tk_write", args: { path: "checks.json", content: variant === "check-threshold-change" ? '{"expected":0}\n' : '{"expected":2,"reviewedMetadata":true}\n' } });
          if (variant === "recovered-tool-error" && writes === 1) tools.unshift({ name: "tk_read", args: { path: "missing-fixture-file.txt" } });
          if (((variant === "critique-revise" && writes === 2) || (variant === "combined-recipes" && writes === 3))) tools[0].args = { path: "answer.json", content: '{\n  "answer": 2\n}\n' };
          if (((variant === "critique-revise" && writes === 2) || (variant === "combined-recipes" && writes === 3))) tools.push({ name: "tk_write", args: { path: "implementation-note.txt", content: "independently reviewed note\n" } });
          answer(res, tools, variant.startsWith("worker-compaction-") ? 31000 : undefined);
        }
      }
      else if(variant === "cancel-after-edit"){heldCandidateResponse=res;res.once("close",()=>{candidateConnectionClosed=true;});}
      else answer(res, [], variant.startsWith("worker-compaction-") ? 31000 : undefined);
    });
  });
  await listenLoopback(server);
  const port = (server.address() as { port: number }).port;
  writeFileSync(join(agentDir, "models.json"), JSON.stringify({ providers: { "fixture-provider": { baseUrl: `http://127.0.0.1:${port}/v1`,
    apiKey: "fixture-key-not-real", api: "openai-completions", models: [{ id: "fixture-model", name: "Fixture", reasoning: false, input: ["text"],
      contextWindow: 32000, maxTokens: 1000, cost: { input: variant === "opinion-different-reviewer"?1:0, output: variant === "opinion-different-reviewer"?1:0, cacheRead: 0, cacheWrite: 0 } }] } } }));
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [pkg], compaction: { enabled: variant.startsWith("worker-compaction-"), ...(variant.startsWith("worker-compaction-") ? { keepRecentTokens: 1, reserveTokens: 1024 } : {}), ...(variant === "summary-hides-failure" ? { keepRecentTokens: 1, reserveTokens: 256 } : {}) }, retry: { enabled: false, provider: { maxRetries: 0 } }, enableInstallTelemetry: false, quietStartup: true }));
  const config = configured();config.recovery.requestTimeoutMs=10000; config.features.interactiveRecovery = variant === "combined-features" || variant === "combined-tool-recovery" || variant === "schedule-floor"; config.features.managedWorkflows = true; config.storage.path = join(state, "runtime.db");
  if(variant === "schedule-resources")config.limits.activeJobsPerRepository=0;
  if(variant === "schedule-no-window"){config.timePolicy.timezone="UTC";config.timePolicy.windows=[{days:[((new Date().getUTCDay()+2)%7)+1],start:"00:00",end:"00:01"}];}
  if (variant.startsWith("packet-overflow")) config.evidence.packetByteBudget = 128;
  if (variant === "multi-job") config.scheduling = { agingMs: 25, priorities: { inspect: 70, fix: 10 } };
  if (variant === "budget-local-verification") {
    config.routes.primary.protected = true; config.budget.protectedAttemptsPerWorkScope = 2;
    config.budget.minimumRequiredStageAttemptReserves["independent-review"] = 0;
  }
  if (variant === "combined-tool-recovery") {
    config.executionProfiles.interactive.tools = ["kernel_task"]; config.executionProfiles.interactive.timeoutMs = 10000; config.recovery.requestTimeoutMs = 10000;
  }
  for (const role of ["worker", "scout", "reviewer"]) {
    config.executionProfiles[role] = { tools: role === "worker" ? ["read", "grep", "find", "ls", "write", "edit"] : ["read", "grep", "find", "ls"], requiredCapabilities: [], timeoutMs: 25000, maxModelTurns: 10, toolTimeoutMs: 10000, thinking: "off" };
    config.roles[role] = { route: "primary", profileRef: role };
  }
  config.verificationBindings.build = { executable: process.execPath, args: ["-e", "JSON.parse(require('fs').readFileSync('answer.json'))"], environment: {}, timeoutMs: 5000, kind: "build", parser: "exit-code", minimumTests: 1 };
  if (usesShared) {
    config.verificationBindings.build.sharedMutableDirectories = [sharedAlias, sharedRoot];
    config.verificationBindings.build.timeoutMs = 20000;
    config.verificationBindings.build.args = ["-e", `const fs=require('node:fs');fs.appendFileSync(${JSON.stringify(join(sharedRoot,"checks.txt"))},'check\\n');fs.writeFileSync(${JSON.stringify(join(root,"shared-check-ready"))},'ready');${variant === "shared-directory-drift" ? `const timer=setInterval(()=>{if(fs.existsSync(${JSON.stringify(join(root,"shared-check-release"))})){clearInterval(timer);process.exit(0);}},10);` : "JSON.parse(fs.readFileSync('answer.json'));"}`];
  }
  if(variant === "deadline-verifier")config.verificationBindings.build={...config.verificationBindings.build,timeoutMs:60000,args:["-e",`const fs=require('node:fs');fs.appendFileSync(${JSON.stringify(join(root,"deadline-effects"))},${JSON.stringify("started\n")});fs.writeFileSync(${JSON.stringify(join(root,"deadline-ready"))},JSON.stringify({pid:process.pid,namespace:fs.readlinkSync('/proc/self/ns/pid')}));setInterval(()=>{},100);`]};

  if(variant.startsWith("cut-verify-"))config.verificationBindings.build={...config.verificationBindings.build,timeoutMs:60000,args:["-e",`const fs=require('node:fs');fs.appendFileSync(${JSON.stringify(join(root,"verify-effects"))},${JSON.stringify("executed\n")});${variant === "cut-verify-C2"?`fs.writeFileSync(${JSON.stringify(join(root,"native-cut.json"))},JSON.stringify({family:"verify",point:"C2",at:Date.now(),sentinel:true}));setInterval(()=>{},100);`:""}`]};

  if (variant === "baseline-environment-failure") config.verificationBindings.build = { ...config.verificationBindings.build, parser: "json", args: ["-e", "console.log(JSON.stringify({tests:1,passed:0,failed:1,skipped:0,failureCategory:'environment'}));process.exit(1)"] };
  if(variant === "silent-build") {
    const marker=join(root,"silent-ready.json"),release=join(root,"silent-release");
    config.verificationBindings.build={...config.verificationBindings.build,timeoutMs:10000,args:["-e",`const fs=require('node:fs');fs.writeFileSync(${JSON.stringify(marker+".tmp")},JSON.stringify({pid:process.pid,namespace:fs.readlinkSync('/proc/self/ns/pid')}));fs.renameSync(${JSON.stringify(marker+".tmp")},${JSON.stringify(marker)});const timer=setInterval(()=>{if(fs.existsSync(${JSON.stringify(release)})){clearInterval(timer);process.exit(0);}},10);`]};
  }
  config.verificationBindings["focused-tests"] = { executable: process.execPath, args: ["-e", "const ok=JSON.parse(require('fs').readFileSync('answer.json')).answer===2;console.log(JSON.stringify({tests:1,passed:ok?1:0,failed:ok?0:1,skipped:0,failureCategory:ok?null:\"implementation\"}));process.exit(ok?0:1)"], environment: {}, timeoutMs: 5000, kind: "tests", parser: "json", minimumTests: 1 };
  if (variant === "verifier-first") holdCandidateVerifier(config, root);
  if (variant.startsWith("cancel-verifier")) {
    const prefix = `const fs=require('node:fs');`;
    config.verificationBindings["focused-tests"].args = ["-e", variant === "cancel-verifier-first"
      ? prefix + `fs.writeFileSync(${JSON.stringify(join(root, "verifier-ready"))},'started');setInterval(()=>{},1000);`
      : prefix + `fs.writeFileSync(${JSON.stringify(join(root, "verifier-completed"))},'completed');console.log(JSON.stringify({tests:1,passed:1,failed:0,skipped:0}));`];
  }
  if (variant === "optional-failure" || variant === "optional-disallowed") {
    config.workflow.allowPartial = variant === "optional-failure";
    config.workflow.optionalChecks.fix = ["optional-check"];
    config.verificationBindings["optional-check"] = { executable: process.execPath, args: ["-e", 'console.log(JSON.stringify({tests:1,passed:0,failed:1,skipped:0}));process.exit(1)'], environment: {}, timeoutMs: 5000, kind: "tests", parser: "json", minimumTests: 1 };
  }
  if (variant.startsWith("fallback") || variant === "same-model-repair" || variant === "combined-recipes" || ["opinion-different-reviewer","opinion-budget","scheduled-explicit"].includes(variant) || variant.startsWith("auto-model") || variant === "history-model") {
    config.features.crossProviderFailover = variant.startsWith("fallback") || variant === "same-model-repair" || variant === "combined-recipes";
    config.routes.backup = { ...config.routes.primary, model: "fixture-backup", quotaGroup: "backup-pool", protected: true };
    config.quotaGroups["backup-pool"] = structuredClone(config.quotaGroups.pool);
    config.allowedRoutes.push("backup"); config.projectRouteApprovals["*"].push("backup");
    config.recovery.chain = [{ id: "primary-short", route: "primary", wait: { mode: "bounded", maxMs: 50 } },
      { id: "backup", route: "backup", wait: { mode: "bounded", maxMs: 5000 } }, { id: "primary-tail", route: "primary", wait: { mode: "forever" } }];
    const models = JSON.parse(readFileSync(join(agentDir, "models.json"), "utf8"));
    models.providers["fixture-provider"].models.push({ ...models.providers["fixture-provider"].models[0], id: "fixture-backup" });
    writeFileSync(join(agentDir, "models.json"), JSON.stringify(models));
  }
  if(variant.startsWith("auto-model")){config.modelPolicy.candidates=["primary","backup"];config.modelPolicy.defaultPreference=["backup","primary"];}

  if(variant === "child-usage"){

    config.usage.accountPlans=[{provider:"fixture-provider",model:"fixture-model",accountPlanRef:"test-plan"}];
    config.usage.priceBooks=[{id:"plan-price",provider:"fixture-provider",model:"fixture-model",accountPlanRef:"test-plan",currency:"CNY",source:"fixture-plan",effectiveFrom:"2026-01-01T00:00:00Z",effectiveUntil:null,timing:"request-start",timezone:"UTC",rates:{input:"1",output:"1",cacheRead:"0",cacheWrite:"0"},windows:[]}];
  }
  if(variant === "history-model"){
    config.modelPolicy.candidates=["primary","backup"];config.modelPolicy.defaultPreference=["primary","backup"];config.modelPolicy.ranking="history-cost";
    config.usage.priceBooks=["fixture-model","fixture-backup"].map(model=>({id:`price-${model}`,provider:"fixture-provider",model,accountPlanRef:null,currency:"USD",source:"synthetic-reference-prices",effectiveFrom:"2026-01-01T00:00:00Z",effectiveUntil:null,timing:"request-start",timezone:"UTC",rates:{input:"1",output:"1",cacheRead:"0",cacheWrite:"0"},windows:[]}));
  }

  if(variant === "fallback-budget-exhausted"){
    config.recovery.chain[1].wait.maxMs=120000;config.budget.backupAttemptsPerIncident=4;
  }
  if (variant.startsWith("fallback-skip")) {
    config.routes.rejected = { ...config.routes.backup, model: "fixture-rejected", network: "rejected-network", quotaGroup: "rejected-pool" };
    config.network["rejected-network"] = variant === "fallback-skip-network" ? { type: "socks5h", endpoint: "socks5h://127.0.0.1:1" } : { type: "direct" };
    config.quotaGroups["rejected-pool"] = structuredClone(config.quotaGroups.pool);
    config.allowedRoutes.push("rejected"); config.projectRouteApprovals["*"].push("rejected");
    config.recovery.chain.splice(1, 0, { id: "rejected-first", route: "rejected", wait: { mode: "bounded", maxMs: 5000 } });
    if (variant === "fallback-skip-telemetry") {
      config.routes.rejected.telemetry = "missing";
      config.telemetryBindings.missing = { path: join(root, "missing-telemetry.json"), accountBinding: config.routes.rejected.accountBinding,
        bucket: "rejected-pool", source: "fixture", freshnessMs: 1000, minimumRemaining: 1 };
    }
    const path = join(agentDir, "models.json"), models = JSON.parse(readFileSync(path, "utf8"));
    models.providers["fixture-provider"].models.push({ ...models.providers["fixture-provider"].models[0], id: "fixture-rejected" });
    if (variant === "fallback-skip-context") {
      config.executionProfiles.worker.minimumContextTokens = 16000;
      models.providers["fixture-provider"].models.find((m: {id: string}) => m.id === "fixture-rejected").contextWindow = 8000;
      models.providers["fixture-provider"].models.find((m: {id: string}) => m.id === "fixture-rejected").maxTokens = 2000;
      models.providers["fixture-provider"].models.find((m: {id: string}) => m.id === "fixture-backup").cost.input = 1;
    }
    if (variant === "fallback-skip-thinking") {
      config.executionProfiles.worker.thinking = "high";
      for (const model of models.providers["fixture-provider"].models) {
        model.reasoning = true; model.thinkingLevelMap = { high: model.id === "fixture-rejected" ? null : "high" };
      }
    }
    writeFileSync(path, JSON.stringify(models));
  }
  if (variant.startsWith("replan-") || ["quota-recovery", "environment-failure", "baseline-environment-failure"].includes(variant)) config.features.semanticReplanning = true;
  if (variant === "replan-zero") config.limits.semanticReplansPerTask = 0;
  if (variant === "multi-job") {
    config.limits.activeJobsPerRepository = 1;
    config.routes.independent = { ...config.routes.primary, model: "fixture-independent", quotaGroup: "independent-pool" };
    config.quotaGroups["independent-pool"] = structuredClone(config.quotaGroups.pool);
    config.allowedRoutes.push("independent"); config.projectRouteApprovals["*"].push("independent");
    config.roles.scout.route = "independent"; config.roles.reviewer.route = "independent";
    const models = JSON.parse(readFileSync(join(agentDir, "models.json"), "utf8"));
    models.providers["fixture-provider"].models.push({ ...models.providers["fixture-provider"].models[0], id: "fixture-independent" });
    writeFileSync(join(agentDir, "models.json"), JSON.stringify(models));
  }
  if(variant === "second-opinion" || variant.startsWith("opinion-") || variant === "deadline-verifier")config.secondOpinion.enabled=true;
  if(variant === "opinion-deadline"){config.executionProfiles.reviewer.timeoutMs=60000;config.recovery.requestTimeoutMs=60000;}
  if(variant === "opinion-off"){config.secondOpinion.enabled=false;config.secondOpinion.model="primary";config.workflow.recipes=["direct","critique"];config.roles.critic={route:"primary",profileRef:"reviewer"};}
  if(variant === "opinion-different-reviewer"){config.secondOpinion.model="backup";config.secondOpinion.reviewTask="CHECK_CONCURRENCY_BOUNDARIES";config.secondOpinion.focus=["concurrency","error handling"];}
  if(variant === "opinion-missing")config.secondOpinion.model="missing-provider/missing-model";
  if(variant === "opinion-readonly")config.secondOpinion.profileRef="worker";
  if(variant === "opinion-request-timeout"){config.executionProfiles.reviewer.timeoutMs=60000;config.recovery.policies.providers["fixture-provider"]={requestTimeout:"2s"};}
  if(variant === "opinion-zero")config.secondOpinion.maxExchanges=0;
  if(variant === "opinion-one"){config.secondOpinion.maxExchanges=1;config.budget.protectedAttemptsPerWorkScope=20;}
  if(variant === "opinion-unresolved")config.budget.protectedAttemptsPerWorkScope=20;
  if(variant === "opinion-disagreement-budget"){config.routes.primary.protected=true;config.budget.protectedAttemptsPerWorkScope=7;}
  if(variant === "opinion-budget"){config.secondOpinion.model="backup";config.routes.primary.protected=true;config.budget.protectedAttemptsPerWorkScope=7;config.budget.minimumRequiredStageAttemptReserves["independent-review"]=4;}
  if(variant === "schedule-window"){config.recovery.requestTimeoutMs=90000;for(const role of ["worker","reviewer"])config.executionProfiles[role].timeoutMs=90000;}
  if (variant === "same-model-repair") { config.workflow.recipes = ["direct"]; config.roles.upgrade = { route: "backup", profileRef: "worker" }; }
  if (variant === "premature-critic" || variant === "critic-reserve" || variant === "critique" || variant === "critique-revise" || variant === "review-reuse") { config.secondOpinion.enabled=true;config.workflow.recipes = ["direct", "critique"]; config.roles.critic = { route: "primary", profileRef: "reviewer" }; }
  if (variant === "critic-reserve") {
    config.routes.primary.protected = true; config.budget.protectedAttemptsPerWorkScope = 6;
    config.budget.minimumRequiredStageAttemptReserves["independent-review"] = 4;
  }
  if (variant === "combined-recipes") {
    config.secondOpinion.enabled=true;
    config.workflow.recipes = ["direct", "critique"];
    config.roles.upgrade = { route: "backup", profileRef: "worker" }; config.roles.critic = { route: "primary", profileRef: "reviewer" };
  }
  if (variant.startsWith("check-")) {
    config.verificationBindings.build.inputs = ["checks.json"]; config.verificationBindings["focused-tests"].inputs = ["checks.json"];
  }
  if(variant === "invalid-plan"){config.workflow.requiredChecks.fix.push("implement");config.verificationBindings.implement={...config.verificationBindings.build};}
  if (variant === "check-threshold-change") config.verificationBindings["focused-tests"].args = ["-e", "const fs=require('fs');const ok=JSON.parse(fs.readFileSync('answer.json')).answer>=JSON.parse(fs.readFileSync('checks.json')).expected;console.log(JSON.stringify({tests:1,passed:ok?1:0,failed:ok?0:1,skipped:0}));process.exit(ok?0:1)"];
  if (variant === "build-repair") config.verificationBindings.build = { ...config.verificationBindings.build, parser: "json", args: ["-e", "try{JSON.parse(require('fs').readFileSync('answer.json'));console.log('{}')}catch{console.log(JSON.stringify({failureCategory:'implementation'}));process.exit(1)}"] };
  if (variant === "environment-failure") config.verificationBindings["focused-tests"].args = ["-e", "console.log(JSON.stringify({tests:1,passed:0,failed:1,skipped:0,failureCategory:'environment'}));process.exit(1)"];
  if (variant === "all-skipped") config.verificationBindings["focused-tests"].args = ["-e", "console.log(JSON.stringify({tests:2,passed:0,failed:0,skipped:2}))"];
  if (variant === "unknown-tests") config.verificationBindings["focused-tests"].args = ["-e", "console.log('Done')"];
  if (variant === "zero-tests" || variant === "summary-hides-failure") config.verificationBindings["focused-tests"].args = ["-e", "console.log(JSON.stringify({tests:0,passed:0,failed:0,skipped:0}))"];
  if (variant === "mutating-check") config.verificationBindings["focused-tests"].args = ["-e", "require('fs').writeFileSync('answer.json','{\"answer\":3}');console.log(JSON.stringify({tests:1,passed:1,failed:0,skipped:0}))"];
  if (variant === "binding-approval") config.routes.primary.protected = true;
  if (variant === "step-cap") config.limits.dispatchedStepsPerJob = 5;
  if (variant === "scope-job-cap") config.limits.jobsPerWorkScope = 1;
  if (variant === "scope-semantic-cap" || variant === "scope-fork-cap") config.limits.semanticAttemptsPerWorkScope = 1;
  if (variant === "writers-disabled-tool" || variant === "inspect") config.limits.writersPerJob = 0;
  if (variant === "writers-disabled-command" || variant === "fix") config.limits.writersPerJob = 4;
  const configPath = join(root, "task-keeper.json"); writeFileSync(configPath, JSON.stringify(config));
  const seededSession = join(root, "seeded-session.jsonl");
  if (variant === "scope-fork-cap") {
    const timestamp = new Date().toISOString();
    writeFileSync(seededSession, [
      { type: "session", version: 3, id: "seed-parent", timestamp, cwd },
      { type: "message", id: "seed-user", parentId: null, timestamp, message: { role: "user", content: [{ type: "text", text: "Historical context before Task Keeper activation" }], timestamp: Date.now() } },
      { type: "message", id: "seed-assistant", parentId: "seed-user", timestamp, message: { role: "assistant", content: [{ type: "text", text: "Historical reply" }], api: "openai-completions", provider: "fixture-provider", model: "fixture-model", stopReason: "stop", timestamp: Date.now(),
        usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } } },
    ].map(value => JSON.stringify(value)).join("\n") + "\n");
  }
  const launch = (sessionId?: string) => spawn(process.execPath, [join(pkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"), "--mode", "rpc", "--no-extensions", "-e", join(pkg, "node_modules/pi-subagents/index.ts"), ...(["details-only-error", "interrupted-zero"].includes(variant) ? ["-e", join(pkg, "tests/fixtures/details-error.ts")] : []), ...(variant === "spawn-failure" ? ["-e", join(pkg, "tests/fixtures/native-spawn-error.ts")] : []), "-e", join(pkg, "index.ts"), "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline", "--provider", "fixture-provider", "--model", "fixture-model", "--thinking", "off", ...((toolEntry || ["scheduled","schedule-missed","opinion-unresolved"].includes(variant) || variant === "proposal-tool" || variant === "proposal-valid" || ["fallback-budget-exhausted", "cancel-after-edit", "workspace-failure", "spawn-failure", "baseline-environment-failure", "fix", "repair", "check-threshold-change", "candidate-edit"].includes(variant) || variant === "terminal-resume" || variant.startsWith("worker-compaction-") || variant === "worker-claim" || variant === "critic-reserve" || variant === "stripped-review-input" || variant === "premature-review" || variant === "forged-artifact" || variant === "scope-fork-cap" || variant === "details-only-error" || variant === "interrupted-zero" || variant === "summary-hides-failure" || variant.startsWith("packet-overflow") || ["zero-tests", "all-skipped", "unknown-tests"].includes(variant)) ? ["--tools", "kernel_task"] : ["--no-tools"]), "--session-dir", join(root, "sessions"), ...(variant === "scope-fork-cap" && !sessionId ? ["--session", seededSession] : []), ...(sessionId ? ["--session-id", sessionId] : [])], {
    cwd, stdio: ["pipe", "pipe", "pipe"], env: { PATH: `${join(pkg, "node_modules/.bin")}:${process.env.PATH}`, LANG: "C.UTF-8", PI_CODING_AGENT_DIR: agentDir, PI_TASK_KEEPER_CONFIG: configPath, TASK_KEEPER_FIXTURE_NATIVE_FAULT: variant === "interrupted-zero" ? "interrupted" : undefined, PI_SUBAGENTS_TEMP_ROOT: join(root, "native-subagents"), PI_MODEL_EXCLUSIONS_PATH: join(root, "native-exclusions.json"), PI_OFFLINE: "1", PI_TELEMETRY: "0" },
  });
  let child = launch();
  let output = "", errors = "", store: Store | undefined;
  const protocolEvents: Record<string, any>[] = []; let protocolBuffer = "";
  const watchChild = () => { child.stdout.on("data", (data) => { output = (output + data).slice(-24000); protocolBuffer += data;
    let newline: number; while ((newline = protocolBuffer.indexOf("\n")) >= 0) {
      const line = protocolBuffer.slice(0, newline); protocolBuffer = protocolBuffer.slice(newline + 1); if (line.trim()) protocolEvents.push(JSON.parse(line));
    } }); child.stderr.on("data", (data) => { errors = (errors + data).slice(-12000); }); };
  watchChild();
  const statusViews=async(jobId:string,name:string)=>{
    statusJobId=jobId;const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:`view-${name}`,type:"prompt",message:`/orch status ${jobId}`})+"\n");let until=Date.now()+10000;while(!protocolEvents.slice(offset).some(e=>e.id===`view-${name}`)){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.slice(offset).filter(e=>e.type==="extension_ui_request"&&e.method==="notify").flatMap(e=>{try{return[JSON.parse(e.message)];}catch{return[];}}).find(e=>e.id===jobId);
    child.stdin.write(JSON.stringify({id:`model-view-${name}`,type:"prompt",message:"Use kernel_task status to explain the current task state"})+"\n");until=Date.now()+10000;
    while(!protocolEvents.slice(offset).some(e=>e.type==="tool_execution_end"&&e.toolName==="kernel_task")||!protocolEvents.slice(offset).some(e=>e.type==="agent_end")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const tool=protocolEvents.slice(offset).find(e=>e.type==="tool_execution_end"&&e.toolName==="kernel_task")!.result;
    return {ui,tool,parentInput:parentInputs.at(-1)};
  };
  t.after(async () => { store?.close(); if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGTERM"); await exit; }
    server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve())); });
  if (variant === "verifier-first") t.after(() => {
    writeFileSync(join(root, "workflow-protocol.json"), JSON.stringify({ protocolEvents, output, errors, parentInputs, requests, writes }, null, 2));
    const destination = join(process.env.TASK_KEEPER_TEST_RESULT_ROOT!, `sch010-${process.env.TASK_KEEPER_SCH010_CUT ? "mutation" : "normal"}-${Date.now()}-${process.pid}`);
    cpSync(root, destination, { recursive: true, filter: path => !path.split("/").includes("node_modules") });
    console.log(`SCH010_ARTIFACT ${destination}`);
  });
  // Cold extension loading is setup, not the scenario's response window. The
  // outer 90-second test limit still bounds setup plus the entire scenario.
  child.stdin.write(JSON.stringify({id:"fixture-ready",type:"get_state"})+"\n");
  const startupDeadline=Date.now()+30000;
  while(!protocolEvents.some(event=>event.type==="response"&&event.id==="fixture-ready")){
    if(Date.now()>startupDeadline||child.exitCode!==null||child.signalCode!==null)throw new Error(JSON.stringify({phase:"Pi startup",pid:child.pid,output,errors}));
    await delay(20);
  }
  assert.equal(protocolEvents.find(event=>event.type==="response"&&event.id==="fixture-ready")!.success,true);
  if(variant === "history-model"){
    child.stdin.write(JSON.stringify({id:"history-catalog",type:"get_available_models"})+"\n");const until=Date.now()+10000;
    while(!protocolEvents.some(event=>event.type==="response"&&event.id==="history-catalog")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const models=protocolEvents.find(event=>event.type==="response"&&event.id==="history-catalog")!.data.models;
    const primary=models.find((model:{id:string})=>model.id==="fixture-model"),backup=models.find((model:{id:string})=>model.id==="fixture-backup");assert.ok(primary);assert.ok(backup);
    const contract=digest([comparisonPolicyDigest(config),null,verificationInputs(config.verificationBindings,cwd).digest,modelBindingDigest(primary),null]);
    const reference=new Store(state),ledger=new UsageLedger(reference),at=Date.now()-60000;
    try{for(const [model,input] of [[primary,20000],[backup,10000]] as const)for(let index=0;index<5;index++){
      const id=`reference-${model.id}-${index}`;ledger.begin({id,sessionId:"synthetic-reference",title:id,workflow:"fix",comparisonGroup:"reference",contractDigest:contract},at);
      ledger.record(sdkUsage({generationId:id,provider:model.provider,model:model.id,modelVersion:modelBindingDigest(model),role:"implement",startedAt:at,endedAt:at+1,usage:{input,output:1000,cacheRead:0,cacheWrite:0},attemptIds:[id],outcome:"success",source:"synthetic-history-reference"}),id);ledger.finish(id,"accepted","verifier",at+2);
    }}finally{reference.close();}
  }
  if(variant === "opinion-unsupported"){
    child.stdin.write(JSON.stringify({id:"ordinary-chat",type:"prompt",message:"Answer normally"})+"\n");const until=Date.now()+10000;
    while(!protocolEvents.some(event=>event.type==="agent_settled")){if(Date.now()>until)throw new Error(output+errors);await delay(20);}
    assert.ok(output.includes("Already streamed ordinary answer"));assert.equal(requests,1);
    child.stdin.write(JSON.stringify({id:"unsupported-opinion",type:"prompt",message:"/orch second-opinion existing streamed chat"})+"\n");
    while(!protocolEvents.some(event=>event.id==="unsupported-opinion")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const observer=new Store(state);try{acceptance("AC15","unsupported-entry",{level:"E",observer:"already-streamed-chat-and-real-command-rejection",predicate:"ordinary output is not falsely held for consensus",artifact:observerArtifact("unsupported-opinion",{output,requests})},()=>{
      assert.ok(output.includes("SECOND_OPINION_REQUIRES_MANAGED_TASK")||output.includes("Existing streamed chat is not held or rewritten"));assert.equal(requests,1);assert.equal(observer.list("managed-jobs").length,0);
    });}finally{observer.close();}return;
  }
  if(variant === "schedule-floor"){
    child.stdin.write(JSON.stringify({id:"quota-source",type:"prompt",message:"Observe the account quota"})+"\n");const observer=new Store(state);try{const until=Date.now()+10000;while(!observer.list<any>("recovery").some(row=>row.value.status==="WAITING_QUOTA")){if(Date.now()>until)throw new Error(output+errors);await delay(20);}assert.ok(scheduleFloor>Date.now());}finally{observer.close();}
    child.stdin.write(JSON.stringify({id:"pause-recovery",type:"prompt",message:"/orch pause"})+"\n");const until=Date.now()+10000;while(!protocolEvents.some(event=>event.id==="pause-recovery")){if(Date.now()>until)throw new Error(output);await delay(20);}
  }
  if(variant === "schedule-window"){
    let remaining=60000-Date.now()%60000;if(remaining<20000)await delay(remaining+100);
    const now=Date.now(),start=new Date(now),end=new Date(Math.floor(now/60000)*60000+60000);windowEnd=end.getTime();
    config.timePolicy={...config.timePolicy,timezone:"UTC",windows:[{days:[start.getUTCDay()||7],start:start.toISOString().slice(11,16),end:end.toISOString().slice(11,16)}]};writeFileSync(configPath,JSON.stringify(config));
  }
  const taskDeadline=Date.now()+(variant === "opinion-deadline"?30000:20000);let deadlineProcess:ReturnType<typeof processIdentity>|null=null;
  const scheduleAt=Date.now()+(variant === "schedule-restart-future"?15000:variant === "scheduled"?10000:variant === "schedule-expired"?1000:2500);let observedQueuedSchedule=false,scheduleRestarted=false;
  child.stdin.write(JSON.stringify({ type: "prompt", message: ["deadline-verifier","opinion-deadline"].includes(variant)?`/orch fix --deadline ${new Date(taskDeadline).toISOString()} -- Set answer to 2` : variant === "history-model"?"/orch fix --auto-model --group reference -- Set answer to 2" : ["auto-model","auto-model-repair"].includes(variant)?"/orch fix --auto-model -- Set answer to 2" : (variant === "scheduled" || variant === "scheduled-explicit" || variant.startsWith("schedule-") || variant === "cut-start-C1") ? `/orch schedule fix ${variant === "scheduled-explicit"?"--model backup ":""}--not-before ${new Date(scheduleAt).toISOString()} ${["schedule-expired","schedule-no-window"].includes(variant)?`--deadline ${new Date(scheduleAt+1000).toISOString()} `:""}-- Set answer to 2` : toolEntry ? "Use kernel_task to prepare the requested candidate" : `/orch ${workflow} ${workflow === "fix" ? "Set answer to 2" + (variant.startsWith("worker-compaction-") ? " Historical synthetic context. ".repeat(600) : "") : "Inspect answer"}`, id: "submit" }) + "\n");
  if(variant === "schedule-no-window"){
    const until=Date.now()+10000;while(!protocolEvents.some(event=>event.id==="submit")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const observer=new Store(state);try{acceptance("AC20","deadline-no-window",{level:"E",observer:"native-submit-and-empty-intent-ledger",predicate:"no permitted start before deadline rejects before work",artifact:observerArtifact(variant,{output,requests,config:config.timePolicy})},()=>{assert.ok(output.includes("NO_TASK_WINDOW_BEFORE_DEADLINE"));assert.equal(requests,0);assert.equal(observer.claims().length,0);assert.equal(observer.list("managed-jobs").length,0);});}finally{observer.close();}return;
  }
  if(variant === "opinion-missing" || variant === "opinion-readonly"){
    const until=Date.now()+10000;while(!protocolEvents.some(event=>event.id==="submit")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const expected=variant === "opinion-missing"?"MODEL_ROUTE_NOT_UNAMBIGUOUS":"SECOND_OPINION_READONLY_REQUIRED";const observer=new Store(state);
    try{acceptance("AC15",variant === "opinion-missing"?"missing-B":"readonly-denial",{level:"E",observer:"native-managed-command-preflight-rejection",predicate:expected,artifact:observerArtifact(variant,{output,requests})},()=>{assert.ok(output.includes(expected));assert.equal(requests,0);assert.equal(observer.list("managed-jobs").length,0);assert.equal(observer.claims().length,0);});}finally{observer.close();}return;
  }
  if (variant.startsWith("writers-disabled-")) {
    const until = Date.now() + 15000;
    const denied = () => toolEntry ? parentToolResults.some(value => value.includes("WRITERS_DISABLED"))
      : protocolEvents.some(event => event.type === "extension_ui_request" && event.method === "notify" && String(event.message).includes("WRITERS_DISABLED"));
    while (!denied() || (toolEntry && !protocolEvents.some(event => event.type === "agent_end"))) {
      if (Date.now() > until) throw new Error(JSON.stringify({ output, errors, parentToolResults })); await delay(20);
    }
    child.stdin.write(JSON.stringify({ id: "writer-doctor", type: "prompt", message: "/orch doctor" }) + "\n");
    while (!protocolEvents.some(event => event.type === "response" && event.id === "writer-doctor")) {
      if (Date.now() > until) throw new Error(output); await delay(20);
    }
    const doctor = protocolEvents.filter(event => event.type === "extension_ui_request" && event.method === "notify")
      .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).filter(value => value.support).at(-1);
    store = new Store(state);
    assert.equal(denied(), true); assert.equal(requests, toolEntry ? 2 : 0); assert.equal(requests, parentRequests); assert.equal(writes, 0);
    assert.equal(store.list("managed-jobs").length, 0); assert.equal(store.list("jobs").length, 0);
    assert.equal(store.list("child-grants").length, 0); assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0);
    assert.deepEqual(store.claims(), []); assert.equal(existsSync(join(state, "worktrees")), false);
    assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs);
    assert.deepEqual(doctor.effectivePolicy.writerPolicy, { configuredLimit: 0, effectiveLimit: 0, mode: "single-writer" });
    assert.equal(doctor.effectivePolicy.limits.writersPerJob, 0); assert.ok(doctor.bindingGaps.fix.includes("limits.writersPerJob"));
    assert.deepEqual(doctor.bindingGaps.inspect, []);
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "writer-observers");
      mkdirSync(path, { recursive: true }); writeFileSync(join(path, `${variant}.json`), JSON.stringify({ events: protocolEvents,
        parentToolResults, doctor, requests, parentRequests, writes, jobs: store.list("managed-jobs"), grants: store.list("child-grants"), claims: store.claims(), refs }, null, 2)); }
    return;
  }
  if(variant === "invalid-plan"){
    const until=Date.now()+15000;while(!protocolEvents.some(event=>event.type==="response"&&event.id==="submit")){if(Date.now()>until)throw new Error(output);await delay(20);}
    store=new Store(state);
    for(const id of ["SCH-004","TK02"]) evidence(id,()=>{
      assert.ok(protocolEvents.some(event=>event.type==="extension_ui_request"&&event.method==="notify"&&String(event.message).includes("DUPLICATE_STEP")),output);
      assert.equal(store!.list("managed-jobs").length,0);assert.equal(store!.list("jobs").length,0);assert.equal(store!.db.prepare("SELECT count(*) n FROM intents").get()!.n,0);
      assert.equal(store!.claims().length,0);assert.equal(existsSync(join(state,"worktrees")),false);assert.equal(requests,0);assert.equal(writes,0);
      assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    });
    acceptance("AC28","invalid-plan",{level:"E",observer:"native-user-submit-and-empty-dispatch-ledger",predicate:"invalid dependency plan rejected before workspace creation",artifact:observerArtifact("invalid-plan",{protocolEvents,requests,writes})},()=>{assert.equal(store!.list("managed-jobs").length,0);assert.equal(store!.db.prepare("SELECT count(*) n FROM intents").get()!.n,0);assert.equal(requests,0);assert.ok(output.includes("DUPLICATE_STEP"));});
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"plan-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"invalid-plan.json"),JSON.stringify({events:protocolEvents,requests,writes,jobs:store.list("managed-jobs"),claims:store.claims()},null,2));}return;
  }
  if (variant === "scope-forged-input") {
    const until=Date.now()+15000;
    while(protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").length<5||parentToolResults.length<5){if(Date.now()>until)throw new Error(JSON.stringify({output,errors,parentInputs}));await delay(20);}
    store=new Store(state);const event=protocolEvents.find(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")!;
    const rejected=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task");
    evidence("SCH-002",()=>{assert.ok(rejected.some(event=>event.isError===true&&JSON.stringify(event.result).includes("workScope")));assert.equal(store!.list("managed-jobs").length,0);});
    for(const id of ["EXE-001","T48"]) evidence(id,()=>{
      assert.equal(rejected.length,5);assert.ok(rejected.every(event=>event.isError===true));
      for(const key of ["context","background"])assert.ok(rejected.some(event=>event.isError===true&&JSON.stringify(event.result).includes(key)));
      assert.equal(store!.list("managed-jobs").length,0);assert.equal(store!.list("child-observations").length,0);assert.equal(requests,2);assert.equal(writes,0);
    });
    acceptance("AC02","model-expansion",{level:"A",observer:"actual-kernel-tool-schema-rejections",predicate:"model cannot enable automatic selection or second opinion",artifact:observerArtifact("model-expansion",{rejected,requests,writes})},()=>{
      for(const key of ["automatic","secondOpinion"])assert.ok(rejected.some(event=>event.isError===true&&JSON.stringify(event.result).includes(key)));
      assert.equal(store!.list("managed-jobs").length,0);assert.equal(store!.list("child-observations").length,0);assert.equal(requests,2);assert.equal(writes,0);
    });
    assert.equal(store.list("managed-jobs").length,0);assert.equal(store.list("jobs").length,0);assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n,0);
    assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n,0);assert.equal(store.claims().length,0);assert.equal(writes,0);assert.equal(reviewRequests,0);assert.equal(requests,2);
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("workScope"));assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    child.stdin.write(JSON.stringify({id:"unsupported-doctor",type:"prompt",message:"/orch doctor"})+"\n");
    while(!protocolEvents.some(event=>event.type==="response"&&event.id==="unsupported-doctor")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const doctor=protocolEvents.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).filter(value=>value.support).at(-1);
    for(const id of ["EXE-001","T48"]) evidence(id,()=>{assert.match(doctor.support.managed,/foreground fresh worktree/);assert.equal(store!.db.prepare("SELECT count(*) n FROM intents").get()!.n,0);});
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"input-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"forged-scope.json"),JSON.stringify({event,rejected,doctor,parentInputs,requests,writes,claims:store.claims()},null,2));}
    return;
  }
  let silentObserved=false;let silentWitness:unknown;
  let bindingPaused = false, bindingRefreshed = false, bindingResumeDenied = false, bindingApproved = false, bindingResumed = false;
  let bindingBudget: unknown;
  let staleReplyReleased = false, staleReplyDenied = false;
  const deadline = Date.now() + (variant === "schedule-window"?120000:75000); let job: ManagedJob | undefined, stopped = false, secondSubmitted = false, pausedViaCommand = false, resumedViaCommand = false, approvalSent = false, approvalResumed = false;
  for (;;) {
    if (!store && existsSync(config.storage.path + ".identity")) store = new Store(state);
    job = store?.list<ManagedJob>("managed-jobs").map((entry) => entry.value).find((entry) => variant !== "multi-job" || entry.workflow === "fix");
    if(variant.startsWith("cut-") && job && existsSync(join(root,"native-cut.json"))){
      const [,family,point]=variant.split("-"),target=family==="start"?"implement":"baseline:build",marker=JSON.parse(readFileSync(join(root,"native-cut.json"),"utf8"));
      const plan=store!.get<{steps:Array<{id:string;status:string;intentId:string|null}>}>("jobs",job.id)!,step=plan.steps.find(step=>step.id===target)!,intent=step.intentId?store!.intent(step.intentId):null;
      const before={job:structuredClone(job),step:structuredClone(step),intent,requests,writes,claims:store!.claims(),marker,effects:existsSync(join(root,"verify-effects"))?readFileSync(join(root,"verify-effects"),"utf8"):""};
      if(point==="C0"){assert.equal(step.status,"pending");assert.equal(intent,null);}else{assert.ok(intent);assert.equal(intent!.status,point==="C1"?"prepared":point==="C2"||point==="C3"?"sent":point==="C4"?"acked":"settled");}
      if(["C0","C1"].includes(point)){if(family==="start"){assert.equal(requests,0);assert.equal(writes,0);}else assert.equal(before.effects,"");}
      else if(family==="start"){assert.equal(writes,1);assert.equal(JSON.parse(readFileSync(join(job.cwd!,"answer.json"),"utf8")).answer,2);}else assert.equal(before.effects,"executed\n");
      const stopped=once(child,"exit"),oldPid=child.pid;child.kill("SIGKILL");await stopped;child=launch(job.parentSessionId);protocolBuffer="";watchChild();
      child.stdin.write(JSON.stringify({id:"cut-restarted",type:"get_state"})+"\n");const until=Date.now()+15000;
      while(!protocolEvents.some(event=>event.type==="response"&&event.id==="cut-restarted")){if(Date.now()>until)throw new Error(output+errors);await delay(20);}await delay(300);
      const restored=store!.get<ManagedJob>("managed-jobs",job.id)!;assert.equal(restored.status,"BLOCKED");assert.equal(requests,before.requests);assert.equal(writes,before.writes);assert.notEqual(child.pid,oldPid);
      if(point==="C5"){
        child.stdin.write(JSON.stringify({id:"cut-resume",type:"prompt",message:`/orch resume ${job.id}`})+"\n");
        const resumedUntil=Date.now()+45000;while(store!.get<ManagedJob>("managed-jobs",job.id)!.status!=="COMPLETED"){if(Date.now()>resumedUntil)throw new Error(JSON.stringify({job:store!.get("managed-jobs",job.id),output,errors}));await delay(20);}
        if(family==="start")assert.equal(writes,1);else {
          assert.equal(readFileSync(join(root,"verify-effects"),"utf8"),"executed\nexecuted\n"); // baseline + required final build
          assert.equal(store!.db.prepare("SELECT count(*) n FROM intents WHERE kind='verify' AND json_extract(payload,'$.stepId')='baseline:build'").get()!.n,1);
        }
      }
      const after=store!.get<ManagedJob>("managed-jobs",job.id)!;
      acceptance("AC27",`${family}.${point}`,{level:"P",observer:"actual-dispatcher-cut-receiver-file-and-restarted-Pi",predicate:`${family}.${point} cannot blindly replay`,artifact:observerArtifact(`native-${family}-${point}`,{before,after,requests,writes,oldPid,newPid:child.pid,claims:store!.claims()})},()=>{
        assert.equal(after.id,before.job.id);assert.equal(after.workScope,before.job.workScope);assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
        if(point==="C5")assert.equal(after.status,"COMPLETED");else{assert.equal(after.status,"BLOCKED");assert.equal(requests,before.requests);assert.equal(writes,before.writes);}
        if(point==="C2")assert.ok(store!.claims().some(claim=>claim.intent_id===before.step.intentId));
      });
      if(variant === "cut-start-C1")acceptance("AC21","crash-intent",{level:"P",observer:"scheduled-native-start-C1-and-actual-Pi-restart",predicate:"crash after intent commit does not duplicate scheduled dispatch",artifact:observerArtifact("schedule-crash-intent",{before,after,requests,writes})},()=>{assert.ok(before.job.options?.notBefore);assert.equal(after.status,"BLOCKED");assert.equal(requests,before.requests);assert.equal(after.workScope,before.job.workScope);assert.equal(store!.intent(before.step.intentId!)!.status,"prepared");});return;
    }
    if(variant === "deadline-verifier" && !deadlineProcess && existsSync(join(root,"deadline-ready"))){
      const ready=JSON.parse(readFileSync(join(root,"deadline-ready"),"utf8"));
      const pid=readdirSync("/proc").filter(id=>/^\d+$/.test(id)).find(id=>{try{return readlinkSync(`/proc/${id}/ns/pid`)===ready.namespace&&Number(/^NSpid:\s+(.+)$/m.exec(readFileSync(`/proc/${id}/status`,"utf8"))?.[1].trim().split(/\s+/).at(-1))===ready.pid;}catch{return false;}});
      assert.ok(pid);deadlineProcess=processIdentity(Number(pid));assert.ok(deadlineProcess);assert.equal(originalProcessStopped(deadlineProcess!),false);
    }
    if(["schedule-restart-future","schedule-missed","schedule-expired"].includes(variant) && job?.status === "QUEUED" && !scheduleRestarted){
      scheduleRestarted=true;const saved=structuredClone(job),oldPid=child.pid;assert.equal(requests,0);assert.equal(store!.claims().length,0);
      const exited=once(child,"exit");child.kill("SIGKILL");await exited;
      if(variant === "schedule-missed" || variant === "schedule-expired")await delay(Math.max(0,scheduleAt-Date.now())+(variant === "schedule-expired"?1500:200));
      acceptance("AC21","exit-before-due",{level:"E",observer:"actual-Pi-exit-with-receiver-still-running",predicate:"no work executes while Pi is absent",artifact:observerArtifact("schedule-offline",{saved,oldPid,requests,at:Date.now()})},()=>{assert.equal(requests,0);assert.equal(store!.claims().length,0);});
      assert.equal(requests,0);assert.equal(store!.get<ManagedJob>("managed-jobs",job.id)!.cwd,null);
      child=launch(job.parentSessionId);protocolBuffer="";watchChild();child.stdin.write(JSON.stringify({id:"schedule-restored",type:"get_state"})+"\n");
      const until=Date.now()+15000;while(!protocolEvents.some(event=>event.type==="response"&&event.id==="schedule-restored")){if(Date.now()>until)throw new Error(errors+output);await delay(20);}
      job=store!.get<ManagedJob>("managed-jobs",saved.id)!;assert.notEqual(child.pid,oldPid);
      if(variant === "schedule-expired"){
        child.stdin.write(JSON.stringify({id:"expired-resume",type:"prompt",message:`/orch resume ${job.id}`})+"\n");while(!protocolEvents.some(event=>event.id==="expired-resume")){if(Date.now()>until)throw new Error(output);await delay(20);}
        acceptance("AC21","expired",{level:"E",observer:"restarted-Pi-deadline-and-user-resume-rejection",predicate:"expired schedule stays unstarted",artifact:observerArtifact("schedule-expired",{job,output,requests})},()=>{assert.notEqual(job!.status,"RUNNING");assert.equal(job!.cwd,null);assert.equal(requests,0);assert.ok(output.includes("TASK_DEADLINE_EXHAUSTED"));assert.equal(store!.claims().length,0);});return;
      }
      if(variant === "schedule-missed"){
        assert.equal(job.status,"PAUSED");assert.equal(job.reason,"scheduled_start_missed_resume_required");assert.equal(requests,0);
        acceptance("AC21","restart-missed",{level:"E",observer:"killed-and-restarted-Pi-plus-receiver",predicate:"missed unstarted schedule pauses without catch-up",artifact:observerArtifact("schedule-missed",{saved,restored:job,oldPid,newPid:child.pid,requests})},()=>{
          assert.equal(job!.id,saved.id);assert.equal(job!.schedule!.admittedAt,null);assert.equal(store!.claims().length,0);assert.equal(requests,0);
        });
        const views=await statusViews(job.id,"missed");acceptance("AC33","missed",{level:"E",observer:"restarted-Pi-user-status-and-actual-parent-tool-result",predicate:"missed start is visible consistently",artifact:observerArtifact("missed-views",views)},()=>{for(const v of [views.ui,views.tool.details,JSON.parse(views.tool.content[0].text)]){assert.equal(v.status,"PAUSED");assert.equal(v.reason,"scheduled_start_missed_resume_required");}assert.ok(JSON.stringify(views.parentInput).includes("scheduled_start_missed_resume_required"));});
        child.stdin.write(JSON.stringify({id:"schedule-resume",type:"prompt",message:`/orch resume ${job.id}`})+"\n");
      }else{assert.equal(job.status,"QUEUED");assert.equal(job.schedule!.notBefore,saved.schedule!.notBefore);}
    }
    if (variant === "verifier-first" && job?.cwd && existsSync(join(root, "freeze-ready.json"))) {
      await contendWithCandidateVerifier({ root, sourcePkg: pkg, agentDir, configPath, job, store: store! });
      assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs);
      return; // The competing writer is an adapter harness: this is P, not a product E claim.
    }
    if(variant === "silent-build" && job && existsSync(join(root,"silent-ready.json")) && !silentObserved) {
      const ready=JSON.parse(readFileSync(join(root,"silent-ready.json"),"utf8"));
      const pid=readdirSync("/proc").filter(id=>/^\d+$/.test(id)).find(id=>{try{return readlinkSync(`/proc/${id}/ns/pid`)===ready.namespace && Number(/^NSpid:\s+(.+)$/m.exec(readFileSync(`/proc/${id}/status`,"utf8"))?.[1].trim().split(/\s+/).at(-1))===ready.pid;}catch{return false;}});
      assert.ok(pid);const stat=readFileSync(`/proc/${pid}/stat`,"utf8");assert.notEqual(stat.slice(stat.lastIndexOf(")")+2).split(" ")[0],"Z");
      const step=store!.get<{steps:Array<{id:string;status:string;intentId:string}>}>("jobs",job.id)!.steps.find(step=>step.id==="baseline:build")!;
      for(const id of ["EXE-013","T16"]) evidence(id,()=>{assert.equal(job!.status,"RUNNING");assert.equal(step.status,"running");assert.equal(store!.intent(step.intentId)!.status,"sent");assert.equal(job!.verification["baseline:build"],undefined);assert.equal(requests,0);assert.equal(existsSync(join(root,"silent-release")),false);});
      const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:"silent-status",type:"prompt",message:`/orch status ${job.id}`})+"\n");const until=Date.now()+10000;
      while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id==="silent-status")){if(Date.now()>until)throw new Error(output);await delay(20);}
      const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id);
      for(const id of ["EXE-013","T16"]) evidence(id,()=>{assert.equal(ui.status,"RUNNING");assert.equal(ui.receipt,null);assert.doesNotThrow(()=>process.kill(Number(pid),0));assert.equal(requests,0);});
      silentWitness={ready,pid,stat,ui,step};silentObserved=true;writeFileSync(join(root,"silent-release"),"continue");
    }
    if (variant === "binding-approval" && job) {
      if (requests > 0 && !bindingPaused) {
        bindingPaused = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch pause ${job.id}`, id: "pause-binding" }) + "\n");
      }
      if (job.status === "PAUSED" && job.jobLease && ["settled", "not_sent"].includes(store!.intent(job.jobLease)?.status ?? "") && !bindingRefreshed) {
        bindingRefreshed = true; bindingBudget = store!.bucket(`work-${job.workScope}`);
        const path = join(agentDir, "models.json"), models = JSON.parse(readFileSync(path, "utf8"));
        models.providers["fixture-provider"].models[0].contextWindow = 64000; writeFileSync(path, JSON.stringify(models));
        child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch refresh-bindings ${job.id}`, id: "refresh-bindings" }) + "\n");
      }
      let preview: { digest: string } | undefined;
      for (const line of output.split("\n")) { try { const event = JSON.parse(line); if (event.type === "extension_ui_request" && event.method === "notify") {
        const value = JSON.parse(event.message); if (value.id === job.id && value.modelBindingChange) preview = value.modelBindingChange;
      } } catch {} }
      if (preview && !bindingResumeDenied) {
        bindingResumeDenied = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch resume ${job.id}`, id: "deny-stale-binding" }) + "\n");
      }
      if (preview && output.includes("MODEL_BINDINGS_CHANGED_REQUIRES_RECONCILIATION") && !bindingApproved) {
        assert.equal(job.status, "PAUSED"); assert.deepEqual(store!.bucket(`work-${job.workScope}`), bindingBudget);
        bindingApproved = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch approve-bindings ${job.id} ${preview.digest}`, id: "approve-binding" }) + "\n");
      }
      if (job.reason === "model_bindings_revision_authorized" && !bindingResumed) {
        assert.deepEqual(store!.bucket(`work-${job.workScope}`), bindingBudget); assert.equal(job.checks.length, 0);
        bindingResumed = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch resume ${job.id}`, id: "resume-binding" }) + "\n");
      }
    }
    if (variant === "model-control-race" && job && heldParentResponse && !pausedViaCommand) {
      pausedViaCommand = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch pause ${job.id}`, id: "pause-old-model" }) + "\n");
    }
    if (variant === "model-control-race" && job?.status === "PAUSED" && heldParentResponse && !staleReplyReleased) {
      staleReplyReleased = true; answer(heldParentResponse, [{ name: "kernel_task", args: { action: "resume", jobId: job.id } }]); heldParentResponse = null;
    }
    if (variant === "model-control-race" && job?.status === "PAUSED" && parentToolResults.some(result => result.includes("MODEL_CONTROL_REVOKED")) && !staleReplyDenied) {
      staleReplyDenied = true;
      for (const id of ["CFG-001", "REC-019"]) evidence(id, () => {
        assert.equal(staleReplyReleased, true); assert.equal(job!.status, "PAUSED"); assert.equal(store!.list("managed-jobs").length, 1);
        assert.ok(parentToolResults.some(result => result.includes("MODEL_CONTROL_REVOKED")));
      });
    }
    if (variant === "model-control-race" && staleReplyDenied && job?.cwd && !resumedViaCommand
      && store?.get<{steps:Array<{status:string}>}>("jobs", job.id)?.steps.every(step => !["running", "unknown"].includes(step.status))) {
      resumedViaCommand = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch resume ${job.id}`, id: "user-resume-after-denial" }) + "\n");
    }
    if ((variant === "tool-entry" || variant.startsWith("snapshot-")) && job && !pausedViaCommand) {
      pausedViaCommand = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch pause ${job.id}`, id: "pause-tool-job" }) + "\n");
    }
    if ((variant === "tool-entry" || variant.startsWith("snapshot-")) && job?.status === "PAUSED" && !!job.cwd && !!store?.get<{ steps: Array<{ status: string }> }>("jobs", job.id)?.steps.every((step) => !["running", "unknown"].includes(step.status)) && !resumedViaCommand) {
      resumedViaCommand = true; assert.equal(job.receipt, null);
      child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch resume ${job.id}`, id: "resume-tool-job" }) + "\n");
    }
    if (variant.startsWith("snapshot-") && job && resumedViaCommand && existsSync(join(root, "snapshot-ready.json"))) {
      const action = variant.split("-")[1], order = variant.endsWith("revoke-first") ? "revoke-first" : "await-first";
      const trace: string[] = ["snapshot-ready"], beforePlan = store!.get<{dispatched:number;paused:boolean}>("jobs", job.id)!;
      const beforeRequests = requests, beforeWrites = writes, ready = JSON.parse(readFileSync(join(root, "snapshot-ready.json"), "utf8"));
      const until = Date.now() + 20000;
      const waitFor = async (check: () => boolean) => { while (!check()) { if (Date.now() > until) throw new Error(JSON.stringify({phase:"snapshot control",variant,output,errors,job:store!.get("managed-jobs",job!.id)})); await delay(10); } };
      const release = () => { trace.push("release"); writeFileSync(join(root, "snapshot-release"), "release actual snapshot result"); };
      const control = async () => {
        trace.push("control");
        child.stdin.write(JSON.stringify(action === "dispose" ? {id:"snapshot-control",type:"new_session"}
          : {id:"snapshot-control",type:"prompt",message:`/orch ${action} ${job!.id}`}) + "\n");
        await waitFor(() => protocolEvents.some(event => event.type === "response" && event.id === "snapshot-control"));
      };
      if (order === "revoke-first") { await control(); release(); }
      else { release(); await waitFor(() => protocolEvents.some(event => event.type === "response" && event.id === "resume-tool-job")); await control(); }
      await waitFor(() => protocolEvents.some(event => event.type === "response" && event.id === "resume-tool-job"));
      await waitFor(() => !store!.get<{steps:Array<{status:string}>}>("jobs", job!.id)!.steps.some(step => step.status === "running"));
      // Step settlement precedes the job's cancellation finalizer. A stopped
      // step alone is not the public CANCELLED acknowledgement.
      if (action === "stop") await waitFor(() => store!.get<ManagedJob>("managed-jobs", job!.id)!.status === "CANCELLED");
      const current = store!.get<ManagedJob>("managed-jobs", job.id)!;
      const plan = store!.get<{dispatched:number;paused:boolean}>("jobs", job.id)!;
      matrixCase("await-orders", `R09.${action}.${order}`, () => {
        assert.equal(ready.jobId, job!.id); assert.ok(ready.snapshot); assert.equal(existsSync(join(root,"snapshot-returned")), true);
        assert.equal(trace.indexOf("control") < trace.indexOf("release"), order === "revoke-first");
        assert.equal(current.status, action === "stop" ? "CANCELLED" : "PAUSED", "SNAPSHOT_REVOKED_CONTROL_MUST_PERSIST"); assert.equal(plan.paused, true);
        assert.notEqual(current.receipt?.status, "COMPLETED"); assert.equal(current.semanticAttempts, 1);
        assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"), '{"answer":1}\n');
        if (order === "revoke-first") { assert.equal(plan.dispatched, beforePlan.dispatched); assert.equal(requests, beforeRequests); assert.equal(writes, beforeWrites);
          if (action !== "dispose") assert.match(output, /RESUME_CONTROL_REVOKED/);
          else assert.equal(protocolEvents.find(event => event.id === "snapshot-control" && event.type === "response")!.success, true); }
        else { assert.ok(plan.dispatched >= beforePlan.dispatched); assert.ok(current.controlEpoch > ready.epoch); }
      });
      if(action === "pause" || action === "stop")acceptance("AC08",action,{level:"E",observer:"actual-snapshot-await-and-native-user-revocation",predicate:`${action}.${order}`,artifact:observerArtifact(`revoke-${action}-${order}`,{ready,trace,beforePlan,plan,current,beforeRequests,requests,beforeWrites,writes})},()=>{assert.equal(current.status,action==="stop"?"CANCELLED":"PAUSED");assert.equal(plan.paused,true);if(order==="revoke-first"){assert.equal(requests,beforeRequests);assert.equal(writes,beforeWrites);}});
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "snapshot-observers"); mkdirSync(path,{recursive:true});
        writeFileSync(join(path,`${variant}.json`),JSON.stringify({ready,trace,beforePlan,plan,current,beforeRequests,requests,beforeWrites,writes,protocolEvents,output,errors},null,2));
        cpSync(join(root,"snapshot-cut-manifest.json"),join(path,`${variant}-manifest.json`));
      }
      return;
    }
    if (variant === "multi-job" && job?.status === "WAITING_QUOTA" && !secondSubmitted) {
      secondSubmitted = true; child.stdin.write(JSON.stringify({ type: "prompt", message: "/orch inspect Inspect the independent task", id: "second" }) + "\n");
    }
    if (variant === "multi-job" && job && !independentCompleted) {
      const second = store?.list<ManagedJob>("managed-jobs").map((entry) => entry.value).find((entry) => entry.workflow === "inspect");
      if (second?.status === "COMPLETED") {
        for (const id of ["REC-022", "SCH-013"]) evidence(id, () => {
          assert.equal(config.limits.activeJobsPerRepository, 1); assert.equal(second.status, "COMPLETED");
          assert.equal(second.workScope, job!.workScope); assert.notEqual(job!.status, "COMPLETED");
          assert.equal(store!.get<{priority:number}>("jobs", second.id)!.priority, 70);
          assert.equal(store!.get<{priority:number}>("jobs", job!.id)!.priority, 10);
          assert.notEqual(store!.get<{ status: string }>("incidents", "pool")?.status, "CLOSED");
          assert.ok(job!.cwd && existsSync(join(job!.cwd, "answer.json"))); assert.ok(job!.snapshot);
          assert.ok(requestedModels.includes("fixture-independent"));
        }); independentCompleted = true;
      }
    }
    if (usesShared && variant !== "shared-directory-drift" && job?.status === "RUNNING" && !sharedReleased) {
      const plan = store!.get<{steps: Array<{id: string; status: string; readyAt: number | null; resources: unknown[]}>}>("jobs", job.id);
      const baseline = plan?.steps.find(step => step.id === "baseline:build");
      if (baseline?.status === "pending" && baseline.readyAt !== null) {
        for (const id of (variant.startsWith("proposal-") ? coverageIds[variant].split(" ") : ["SCH-009", "TK05"])) evidence(id, () => {
          assert.equal(requests, 0); assert.equal(existsSync(join(sharedRoot, "checks.txt")), false);
          assert.equal(store!.claims().filter(claim => String(claim.resource_id).startsWith("shared-directory-")).length, 1);
          assert.equal(store!.claims().find(claim => String(claim.resource_id).startsWith("shared-directory-"))!.intent_id, sharedIntent);
          assert.ok(job!.sharedWriteResources?.build.length); assert.equal(baseline.status, "pending");
        });
        if (variant.startsWith("proposal-")) {
          const query = async (id: string, message: string) => {
            const offset = protocolEvents.length; child.stdin.write(JSON.stringify({ type: "prompt", id, message }) + "\n");
            const until = Date.now() + 15000;
            while (!protocolEvents.slice(offset).some(event => event.type === "response" && event.id === id)) { if (Date.now() > until) throw new Error(output); await delay(20); }
            const notices = protocolEvents.slice(offset).filter(event => event.type === "extension_ui_request" && event.method === "notify").map(event => String(event.message));
            proposalWitness.push({ id, notices }); return notices;
          };
          if (variant === "proposal-tool") {
            proposalModelJob = job.id;
            child.stdin.write(JSON.stringify({ type: "prompt", id: "model-proposal", message: "Inspect the current decision packet and propose its permitted baseline verification." }) + "\n");
            const until = Date.now() + 15000;
            while (!parentToolResults.some(value => { try { return !!JSON.parse(JSON.parse(value)).contract; } catch { return false; } }) || !protocolEvents.some(event => event.type === "agent_end")) {
              if (Date.now() > until) throw new Error(JSON.stringify({ output, errors, parentToolResults })); await delay(20);
            }
          } else {
            const views = await query("decision-packet", `/orch decisions ${job.id}`), view = views.map(value => JSON.parse(value)).find(value => value.packet);
            assert.ok(view?.packet); assert.ok(view.allowed.some((target: any) => target.action === "verify" && target.target === "baseline:build"));
            const proposal = { packetId: view.packet.id, action: "verify", target: "baseline:build", reason: "Use verified fixed requirements", evidenceIds: [] };
            if (variant === "proposal-valid") { const invalid = await query("invalid-proposal", `/orch propose ${job.id} ${JSON.stringify({ ...proposal, action: "shell" })}`); evidence("EVD-009", () => assert.ok(invalid.some(value => value.includes("INVALID_PROPOSAL")))); }
            if (variant === "proposal-valid") {
              const rootRequired = [...store!.get<{spec:{required:string[]}}>("jobs", job.id)!.spec.required];
              const heartbeats: unknown[] = [];
              for (let i = 0; i < 2; i++) {
                const observed = once(sharedHolder!, "message", {signal:AbortSignal.timeout(10000)}); sharedHolder!.send("heartbeat");
                const [heartbeat] = await observed; heartbeats.push(heartbeat);
                evidence("T60", () => { assert.equal(heartbeat.type, "heartbeat"); assert.equal(heartbeat.observation.heartbeatSequence, i + 1); assert.equal(heartbeat.observation.identity.pid, sharedHolder!.pid); });
              }
              const afterHeartbeat = (await query("heartbeat-packet", `/orch decisions ${job.id}`)).map(value => JSON.parse(value)).find(value => value.packet);
              evidence("T60", () => { assert.equal(afterHeartbeat.packet.id, view.packet.id); assert.equal(afterHeartbeat.packet.decisionRevision, view.packet.decisionRevision); assert.equal(requests, 0); });
              // Supply a settled accounting observation at the trusted ledger
              // boundary. This does NOT execute or certify the P4 online Advisor.
              const accountingIntent = "fixture-advisory-accounting", accountingRequest = "fixture-advisory-request", owner = store!.owner(job.workScope)!;
              store!.prepare(owner, accountingIntent, "accounting-fixture", { source: "synthetic settled accounting input; no native Advisor send claim" });
              store!.reserveRequest(owner, accountingIntent, accountingRequest, [{id:`work-${job.workScope}`,ceiling:config.budget.protectedAttemptsPerWorkScope}]);
              store!.markSent(owner, accountingIntent); store!.settleRequest(accountingRequest, "sent"); store!.settle(accountingIntent, "terminated");
              const afterAccounting = (await query("accounting-packet", `/orch decisions ${job.id}`)).map(value => JSON.parse(value)).find(value => value.packet);
              for (const id of ["RTB-019", "T85"]) evidence(id, () => {
                assert.equal(config.advisor.mode, "off"); assert.equal(afterAccounting.packet.id, view.packet.id);
                assert.equal(afterAccounting.packet.decisionRevision, view.packet.decisionRevision); assert.equal(afterAccounting.packet.budget.available, view.packet.budget.available - 1);
                const bucket = store!.bucket(`work-${job!.workScope}`)!; assert.equal(bucket.ceiling, 12); assert.equal(bucket.used, 1); assert.equal(bucket.reserved, 0); assert.equal(requests, 0);
              });
              proposalWitness.push({ kind: "non-semantic-observations", heartbeats, afterHeartbeat, afterAccounting,
                accountingBoundary: "synthetic producer observation, actual Pi consumer; online Advisor remains unsupported" });
              for (const [index, item] of [
                { id: "T62", patch: { required: [] } },
                { id: "T63", patch: { shell: `touch ${join(root, "untrusted-proposal-executed")}` } },
                { id: "T63", patch: { provider: "unbound-provider" } },
              ].entries()) {
                const rejected = await query(`illegal-field-${index}`, `/orch propose ${job.id} ${JSON.stringify({ ...proposal, ...item.patch })}`);
                evidence(item.id, () => {
                  assert.ok(rejected.some(value => value.includes("UNKNOWN_FIELD")));
                  assert.deepEqual(store!.get<{spec:{required:string[]};dispatched:number}>("jobs", job!.id)!.spec.required, rootRequired);
                  assert.equal(store!.get<{dispatched:number}>("jobs", job!.id)!.dispatched, 0); assert.equal(store!.list("proposals").length, 0);
                  assert.equal(existsSync(join(root, "untrusted-proposal-executed")), false); assert.equal(requests, 0);
                });
              }
              for (const [index, invalidJson] of ["", "{", "{} {}", '"unterminated'].entries()) {
                const rejected = await query(`bad-json-${index}`, `/orch propose ${job.id} ${invalidJson}`);
                evidence("T64", () => {
                  assert.ok(rejected.some(value => value.includes("INVALID_PROPOSAL_JSON")));
                  const invalid = store!.list<{reason:string;status:string;jobId:string}>("proposal-rejections").filter(row => row.value.reason === "INVALID_PROPOSAL_JSON");
                  assert.equal(invalid.length, index + 1); assert.ok(invalid.every(row => row.value.status === "invalid" && row.value.jobId === job!.id));
                  assert.equal(store!.list("proposals").length, 0); assert.equal(store!.list("child-grants").length, 0);
                  assert.equal(store!.get<{dispatched:number}>("jobs", job!.id)!.dispatched, 0); assert.equal(requests, 0);
                });
              }
              const refreshed = (await query("after-invalid-observations", `/orch decisions ${job.id}`)).map(value => JSON.parse(value)).find(value => value.packet);
              assert.equal(refreshed.packet.id, view.packet.id); assert.equal(refreshed.proposalRejections.total, 8);
              await query("pause-proposal-owner", `/orch pause ${job.id}`);
              await query("resume-proposal-owner", `/orch resume ${job.id}`);
              const revoked = await query("old-proposal-after-control", `/orch propose ${job.id} ${JSON.stringify(proposal)}`);
              const refreshedControl = (await query("new-control-packet", `/orch decisions ${job.id}`)).map(value => JSON.parse(value)).find(value => value.packet);
              evidence("T70", () => {
                assert.ok(revoked.some(value => value.includes("INVALID_PROPOSAL"))); assert.notEqual(refreshedControl.packet.id, view.packet.id);
                assert.equal(store!.list("proposals").length, 0); assert.equal(store!.list("proposal-executions").length, 0);
                assert.equal(store!.get<{dispatched:number}>("jobs", job!.id)!.dispatched, 0); assert.equal(requests, 0);
                assert.deepEqual(store!.get<{spec:{required:string[]}}>("jobs", job!.id)!.spec.required, rootRequired);
              });
              proposal.packetId = refreshedControl.packet.id;
              const finish = await query("finish-with-required-pending", `/orch propose ${job.id} ${JSON.stringify({ ...proposal, action: "request_finish", target: job.id })}`);
              const result = finish.map(value => JSON.parse(value)).find(value => value.contract);
              assert.equal(result.job.status, "RUNNING"); assert.equal(result.job.receipt, null);
              assert.equal(store!.get<{dispatched:number}>("jobs", job.id)!.dispatched, 0);
              assert.ok(view.packet.blockers.some((reason: string) => reason.includes("required:")));
            }
            const accepted = await query("accepted-proposal", `/orch propose ${job.id} ${JSON.stringify(proposal)}`); assert.ok(accepted.some(value => value.includes('"contract"')));
            if (variant === "proposal-valid") {
              const repeated = await query("duplicate-proposal", `/orch propose ${job.id} ${JSON.stringify({ ...proposal, reason: "Same decision with different wording" })}`);
              for (const id of ["EVD-009", "T65"]) evidence(id, () => {
                assert.ok(repeated.some(value => value.includes("DUPLICATE_PROPOSAL"))); assert.equal(store!.list("proposals").length, 2);
                assert.equal(store!.get<{dispatched:number}>("jobs", job!.id)!.dispatched, 0); assert.equal(store!.list("proposal-executions").length, 0); assert.equal(requests, 0);
              });
            }
          }
          const pending = store!.get<{fingerprint: string}>("pending-proposals", job.id); assert.ok(pending); assert.equal(store!.list("proposals").length, variant === "proposal-valid" ? 2 : 1);
          assert.equal(store!.get<{dispatched: number}>("jobs", job.id)!.dispatched, 0);
          proposalWitness.push({ pending, grants: store!.list("child-grants"), job });
          if (variant === "proposal-stale") writeFileSync(join(job.cwd!, "answer.json"), '{"answer":3}\n');
        }
        store!.settle(sharedIntent!, "unknown"); sharedObservations.push({ kind: "blocked-baseline", job, plan, claims: store!.claims() });
        const exit = once(sharedHolder!, "exit"); sharedHolder!.kill("SIGKILL"); await exit;
        assert.equal(sharedHolder!.signalCode, "SIGKILL"); store!.settle(sharedIntent!, "terminated"); sharedReleased = true;
      }
    }
    if (variant === "shared-directory-drift" && job && existsSync(join(root, "shared-check-ready")) && !sharedRetargeted) {
      const other = join(root, "different-shared-root"); mkdirSync(other); unlinkSync(sharedAlias); symlinkSync(other, sharedAlias);
      sharedRetargeted = true; writeFileSync(join(root, "shared-check-release"), "release");
    }
    if (variant.startsWith("cancel-verifier") && job && existsSync(join(root, "verifier-ready")) && !stopped) {
      stopped = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch stop ${job.id}`, id: "cancel-at-verifier" }) + "\n");
    }
    if (variant === "cancel-verifier-late" && job?.cancelRequested) writeFileSync(join(root, "verifier-release"), "observe late completion after cancellation");
    if(variant === "cancel-after-edit" && job?.cwd && heldCandidateResponse && !stopped){
      assert.equal(readFileSync(join(job.cwd,"answer.json"),"utf8"),'{"answer":2}\n');
      assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
      stopped=true;child.stdin.write(JSON.stringify({type:"prompt",message:`/orch stop ${job.id}`,id:"stop-after-edit"})+"\n");
    }
    if (variant === "cancel" && job && requests > 0 && !stopped) {
      stopped = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch stop ${job.id}`, id: "stop" }) + "\n");
    }
    if (variant === "check-approval" && job?.checkInputChange && job.status === "BLOCKED" && !approvalSent) {
      approvalSent = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch approve-checks ${job.id} ${job.checkInputChange.digest}`, id: "approve-checks" }) + "\n");
    }
    if (variant === "check-approval" && job?.reason === "acceptance_revision_authorized" && !approvalResumed) {
      approvalResumed = true; child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch resume ${job.id}`, id: "resume-approved" }) + "\n");
    }
    if (variant === "check-approval" && job?.status === "BLOCKED" && approvalSent && (job.checkInputChange || job.reason === "acceptance_revision_authorized")) {
      if (Date.now() > deadline) throw new Error(JSON.stringify(job)); await delay(30); continue;
    }
    if(variant === "fallback-budget-exhausted" && job?.status === "WAITING_QUOTA" && job.recovery?.stage?.stageId === "primary-tail" && budgetLimitCounts.backup===4)break;
    if(variant === "opinion-restart" && opinionHeld && job && !opinionControlSent){
      opinionControlSent=true;const before=structuredClone(job),beforeRequests=requests,oldPid=child.pid;const plan=store!.get<any>("jobs",job.id),intentId=plan.steps.find((s:any)=>s.id==="second-opinion").intentId;assert.ok(intentId);
      const exit=once(child,"exit");child.kill("SIGKILL");await exit;child=launch(job.parentSessionId);protocolBuffer="";watchChild();child.stdin.write(JSON.stringify({id:"B-restarted",type:"get_state"})+"\n");const until=Date.now()+15000;while(!protocolEvents.some(e=>e.id==="B-restarted")){if(Date.now()>until)throw new Error(output+errors);await delay(20);}await delay(500);job=store!.get<ManagedJob>("managed-jobs",before.id)!;
      acceptance("AC17","restart-unknown",{level:"E",observer:"killed-parent-during-B-request-and-actual-Pi-restart",predicate:"unacknowledged B is not replayed or counted as agreement",artifact:observerArtifact(variant,{before,job,beforeRequests,requests,oldPid,newPid:child.pid,intent:store!.intent(intentId),claims:store!.claims()})},()=>{assert.equal(job!.status,"BLOCKED");assert.equal(job!.reason,"restart_reconciliation_required");assert.equal(requests,beforeRequests);assert.equal(job!.opinion!.exchanges,before.opinion!.exchanges);assert.equal(job!.opinion!.reviews.length,0);assert.equal(job!.workScope,before.workScope);assert.equal(writes,1);assert.ok(store!.claims().some(c=>c.intent_id===intentId));});return;
    }
    if(variant === "schedule-floor" && job && Date.now()<scheduleFloor){observedFloorQueue=true;assert.equal(job.status,"QUEUED");assert.equal(job.cwd,null);assert.equal(job.jobLease,null);assert.equal(requests,1);}
    if(variant === "opinion-cancel" && opinionHeld && job && !opinionControlSent){opinionControlSent=true;child.stdin.write(JSON.stringify({id:"stop-B",type:"prompt",message:`/orch stop ${job.id}`})+"\n");}
    if(variant === "schedule-resources" && job && Date.now()>scheduleAt+300){
      const queued=structuredClone(job);assert.equal(job.status,"QUEUED");
      for(const action of ["pause","resume","stop"]){child.stdin.write(JSON.stringify({id:`scheduled-${action}`,type:"prompt",message:`/orch ${action} ${job.id}`})+"\n");const until=Date.now()+10000;while(!protocolEvents.some(event=>event.id===`scheduled-${action}`)){if(Date.now()>until)throw new Error(output);await delay(20);}job=store!.get<ManagedJob>("managed-jobs",job.id)!;assert.equal(job.status,action==="pause"?"PAUSED":action==="resume"?"QUEUED":"CANCELLED");}
      for(const [ac,name] of [["AC20","resources-denied"],["AC21","pause-stop"]])acceptance(ac,name,{level:"E",observer:"native-due-queue-with-zero-resource-limit",predicate:name,artifact:observerArtifact(name,{queued,job,requests,output})},()=>{assert.equal(requests,0);assert.equal(job!.cwd,null);assert.equal(job!.jobLease,null);assert.equal(store!.claims().length,0);assert.equal(job!.status,"CANCELLED");});return;
    }
    if(variant === "scheduled" && job && Date.now()<scheduleAt){
      observedQueuedSchedule=true;assert.equal(job.status,"QUEUED");assert.equal(job.cwd,null);assert.equal(job.jobLease,null);assert.equal(requests,parentRequests);assert.equal(store!.claims().length,0);
      if(!scheduleStatusShown){scheduleStatusShown=true;const views=await statusViews(job.id,"scheduled");acceptance("AC33","waiting-schedule",{level:"E",observer:"real-scheduled-command-and-parent-kernel-task-status",predicate:"waiting schedule has same due time and no activity in both views",artifact:observerArtifact("schedule-views",views)},()=>{for(const v of [views.ui,views.tool.details,JSON.parse(views.tool.content[0].text)]){assert.equal(v.status,"QUEUED");assert.equal(v.schedule.notBefore,scheduleAt);assert.equal(v.schedule.admittedAt,null);}assert.ok(JSON.stringify(views.parentInput).includes(String(scheduleAt)));});}
    }
    if (job && ["COMPLETED", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"].includes(job.status)) break;
    if (Date.now() > deadline || child.exitCode !== null) throw new Error(JSON.stringify({ job, requests, output, errors }));
    await delay(30);
  }
  if(variant === "history-model"){
    const attempts=store!.events(job!.workScope).filter(event=>event.kind==="http_attempt");
    acceptance("AC23","no-exploration",{level:"E",observer:"all-receiver-calls-matched-to-owned-child-events",predicate:"selection adds no exploratory model call",artifact:observerArtifact("no-exploration",{requests,attempts,selection:job!.modelSelection})},()=>{assert.equal(attempts.length,requests);assert.equal(job!.modelSelection!.reason,"history-cost");assert.ok(attempts.length>0);});
  }
  if(variant === "history-model")acceptance("AC23","history-comparable",{level:"E",observer:"fixed-reference-ledger-and-real-Pi-selection",predicate:"five comparable samples per model override configured order without exploratory calls",artifact:observerArtifact("history-model",{job,requestedModels,requests})},()=>{
    assert.equal(job!.status,"COMPLETED");assert.equal(config.modelPolicy.defaultPreference[0],"primary");assert.equal(job!.modelSelection!.reason,"history-cost");assert.equal(job!.modelSelection!.selected,"backup");
    assert.equal(job!.modelSelection!.sampleIds.length,10);assert.equal(job!.modelSelection!.quoteIds.length,2);assert.equal(job!.modelSelection!.referenceInputBand,"8k-32k");assert.equal(job!.modelSelection!.assessed.length,2);
  });
  if(variant.startsWith("auto-model")){
    const acVariant=variant === "auto-model-off"?"auto-off":variant === "auto-model-repair"?"pin-after-start":"task-opt-in";
    acceptance("AC22",acVariant,{level:"E",observer:"actual-submit-option-and-model-receiver",predicate:"model choice is explicit and fixed for the task",artifact:observerArtifact(`selection-${variant}`,{job,requestedModels})},()=>{
      assert.equal(config.modelPolicy.automaticSelection,false);assert.equal(job!.status,"COMPLETED");assert.equal(job!.modelSelection!.selected,variant === "auto-model-off"?"primary":"backup");
      if(variant === "auto-model-off")assert.equal(requestedModels.includes("fixture-backup"),false);else assert.ok(requestedModels.includes("fixture-backup"));
      if(variant === "auto-model-repair"){assert.equal(job!.semanticAttempts,2);assert.equal(job!.routes!.implement,"backup");assert.equal(job!.upgradesUsed??0,0);}
    });
    if(variant === "auto-model-repair")acceptance("AC23","no-cascade",{level:"E",observer:"actual-repair-on-pinned-model",predicate:"historical selection cannot trigger an in-task quality upgrade",artifact:observerArtifact("history-no-cascade",{job,requestedModels})},()=>{
      assert.equal(job!.semanticAttempts,2);assert.equal(job!.routes!.implement,"backup");assert.equal(job!.upgradesUsed??0,0);
    });
  }
  if(variant === "opinion-different-reviewer"){
    const row=new UsageLedger(store!).query({taskId:job!.id})[0];
    acceptance("AC12","opinion-and-review",{level:"E",observer:"receiver-token-values-and-actual-role-subtotals",predicate:"A, B and separate required reviewer all contribute once",artifact:observerArtifact("opinion-role-costs",{row,requests,requestedModels})},()=>{
      assert.ok(row.byRole.implement.generations>0);assert.ok(row.byRole["second-opinion"].generations>0);assert.ok(row.byRole["independent-review"].generations>0);
      assert.equal(row.knownTokens.input+row.knownTokens.output,requests*110);assert.equal(Object.values(row.byRole).reduce((sum,item)=>sum+item.knownTokens.input+item.knownTokens.output,0),requests*110);
      assert.equal(Object.values(row.byModel).reduce((sum,item)=>sum+item.generations,0),requests);assert.equal(row.unknownCosts,0);
    });
  }
  if(variant === "opinion-different-reviewer")for(const acVariant of ["configured-B","review-task"])acceptance("AC15",acVariant,{level:"E",observer:"actual-B-model-and-trusted-review-prompt",predicate:acVariant,artifact:observerArtifact(`B-${acVariant}`,{job,requestedModels,reviewInputs})},()=>{
    assert.equal(job!.opinion!.route,"backup");assert.ok(requestedModels.includes("fixture-backup"));assert.ok(reviewInputs.some(input=>JSON.stringify(input).includes("TASK_KEEPER_SECOND_OPINION")&&JSON.stringify(input).includes("CHECK_CONCURRENCY_BOUNDARIES")));
    assert.ok(reviewInputs.some(input=>JSON.stringify(input).includes("concurrency, error handling")));
  });
  if(variant === "opinion-different-reviewer")acceptance("AC18","different-required-role",{level:"E",observer:"actual-B-and-required-reviewer-models",predicate:"different reviewer binding requires a separate review",artifact:observerArtifact("different-reviewer",{job,requestedModels,reviewInputs})},()=>{
    assert.equal(job!.status,"COMPLETED");assert.ok(requestedModels.includes("fixture-backup"));assert.equal(job!.outputs.reviewReuse,undefined);
    assert.ok(job!.checks.some(check=>check.checkId==="second-opinion"&&check.status==="passed"));assert.ok(job!.checks.some(check=>check.checkId==="independent-review"&&check.status==="passed"));
    assert.equal(job!.opinion!.route,"backup");assert.ok(reviewInputs.some(input=>JSON.stringify(input).includes("TASK_KEEPER_SECOND_OPINION")));assert.ok(reviewRequests>criticRequests);
  });
  if(variant === "opinion-stale-checks"){
    assert.equal(job!.status,"COMPLETED");assert.equal(job!.opinion!.reviews.at(-1)!.passed,true);
    const original=store!.get<{spec:TaskSpec}>("jobs",job!.id)!.spec;
    const facts:ExecutionFacts={delivery:"started",nativeRunId:job!.id,execution:"ended",nativeStatus:"independent-recheck",terminationConfirmed:true,contract:{requested:{workflow:"fix"},resolved:{workflow:"fix"},runtimeObserved:{workflow:"fix"},violations:[]},observation:{complete:true,gaps:[]},unknownMutators:[],failures:job!.failures,checks:job!.checks,claims:["A and B passed the earlier candidate"]};
    const staleContract=outcome({...original,version:original.version+1},facts);
    acceptance("AC16","stale-contract",{level:"S",observer:"actual-A-B-receipts-under-a-new-contract-version",predicate:"old approval cannot satisfy a new root contract",artifact:observerArtifact("stale-opinion-contract",{original,staleContract,checks:job!.checks})},()=>{assert.equal(staleContract.status,"BLOCKED");assert.ok(staleContract.reasons.some(reason=>reason.startsWith("required:")));});
    writeFileSync(join(job!.cwd!,"answer.json"),'{"answer":0}\n');const snapshot=sourceSnapshot(job!.cwd!).id,changed={...original,snapshot,version:original.version+1};
    const verification=await runVerification("focused-tests",config.verificationBindings,{jobId:job!.id,snapshot,cwd:job!.cwd!});assert.equal(verification.status,"failed");assert.equal(verification.terminationConfirmed,true);
    const artifact=new Artifacts(store!).pin(job!.id,snapshot,JSON.stringify(verification),"verifier");
    const current=outcome(changed,{...facts,checks:[...job!.checks.filter(check=>check.checkId!=="focused-tests"),{checkId:"focused-tests",status:"failed",snapshot,specVersion:changed.version,policyDigest:changed.policyDigest,source:"verifier",artifactId:artifact.id}]});
    for(const acVariant of ["stale-snapshot","both-pass-tests-fail"])acceptance("AC16",acVariant,{level:"P",observer:"real-previous-A-B-approval-and-real-failing-verifier",predicate:"previous agreement cannot override current failed checks",artifact:observerArtifact(acVariant,{job,changed,verification,current})},()=>{
      assert.notEqual(snapshot,original.snapshot);assert.equal(job!.opinion!.reviews.at(-1)!.passed,true);assert.equal(current.status,"BLOCKED");assert.ok(current.reasons.includes("required:focused-tests"));assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    });return;
  }
  if(variant === "opinion-off")for(const [ac,acVariant] of [["AC15","off"],["AC02","opinion-off"],["AC18","disabled-extra-required-kept"]])acceptance(ac,acVariant,{level:"E",observer:"managed-native-review-requests-and-fixed-plan",predicate:"disabled second opinion cannot be enabled by legacy recipe",artifact:observerArtifact(`opinion-off-${ac}`,{job,requests,criticRequests,reviewInputs})},()=>{
    assert.equal(job!.status,"COMPLETED");assert.equal(job!.opinion,undefined);assert.equal(criticRequests,0);assert.ok(job!.checks.some(check=>check.checkId==="independent-review"&&check.status==="passed"));
    assert.equal(store!.get<{steps:Array<{id:string}>}>("jobs",job!.id)!.steps.some(step=>["second-opinion","optional-critique"].includes(step.id)),false);
  });
  if(["schedule-restart-future","schedule-missed"].includes(variant))acceptance("AC21",variant === "schedule-missed"?"explicit-resume":"restart-future",{level:"E",observer:"restarted-native-Pi-and-one-workspace-intent",predicate:"same scheduled job completes exactly once",artifact:observerArtifact(variant,{job,scheduleRestarted,requests,protocolEvents})},()=>{
    assert.equal(scheduleRestarted,true);assert.equal(job!.status,"COMPLETED");assert.equal(store!.list("managed-jobs").length,1);assert.equal(store!.db.prepare("SELECT count(*) n FROM intents WHERE kind='workspace-create'").get()!.n,1);
  });
  if(variant === "child-usage"){
    const planFacts=new UsageLedger(store!).facts(job!.id);assert.ok(planFacts.length>0);assert.ok(planFacts.every(fact=>fact.accountPlanRef==="test-plan"&&fact.cost.currency==="CNY"&&fact.cost.quoteId==="plan-price"));
    const ledger=new UsageLedger(store!),facts=ledger.facts(job!.id),totals=ledger.query({taskId:job!.id})[0];
    acceptance("AC10","child",{level:"E",observer:"child-SDK-forwarded-IDs-and-receiver-usage",predicate:"each receiver generation reports 100 input and 10 output exactly once",artifact:observerArtifact("child-usage",{facts,totals,requests})},()=>{
      assert.equal(facts.length,requests);assert.equal(totals.tokens.input,requests*100);assert.equal(totals.tokens.output,requests*10);assert.equal(totals.task.status,"accepted");
      assert.ok(facts.every(fact=>fact.provider==="fixture-provider"&&fact.model==="fixture-model"));assert.ok(totals.rounds.tools>0);
      const forwarded=store!.list<{usageIds?:string[]}>("child-observations").flatMap(row=>row.value.usageIds??[]);assert.equal(new Set(forwarded).size,requests);
      assert.deepEqual(new Set(facts.map(fact=>fact.id)),new Set(forwarded));
    });
    const budget=store!.db.prepare("SELECT * FROM requests").all(),rawCount=store!.list("usage-facts").length;
    const replay=facts.flatMap(fact=>[ledger.record(fact,job!.id),ledger.record(fact,job!.id)]);
    acceptance("AC10","duplicate-forward",{level:"S",observer:"replayed-real-child-usage-identities",predicate:"duplicate forwarding cannot add another contribution",artifact:observerArtifact("child-duplicate-forward",{replay,rows:ledger.query({taskId:job!.id})})},()=>{
      assert.ok(replay.every(value=>value==="duplicate"));assert.equal(ledger.facts(job!.id).length,requests);assert.equal(store!.list("usage-facts").length,rawCount);assert.deepEqual(store!.db.prepare("SELECT * FROM requests").all(),budget);
    });
    const first=facts[0],corrected={...first,id:`correction-${first.id}`,revision:first.revision+1,supersedes:first.id,source:"declared-correction-fixture",tokens:{...first.tokens,input:first.tokens.input!+5},rawUsage:{...first.rawUsage!,buckets:{...first.rawUsage!.buckets,input:first.tokens.input!+5},totalTokens:first.rawUsage!.totalTokens!+5}};
    ledger.record(corrected,job!.id);const revised=ledger.query({taskId:job!.id})[0];
    acceptance("AC10","revision",{level:"S",observer:"real-source-fact-with-declared-metering-revision",predicate:"only the latest revision contributes",artifact:observerArtifact("child-usage-revision",{first,corrected,revised})},()=>{
      assert.equal(revised.tokens.input,requests*100+5);assert.equal(revised.generations,requests);assert.equal(store!.list("usage-facts").length,rawCount+1);
    });
    acceptance("AC10","conflict",{level:"S",observer:"conflicting-replay-of-recorded-child-fact",predicate:"same source identity with different contents is rejected",artifact:observerArtifact("child-usage-conflict",{source:first.id,unchanged:revised})},()=>{
      assert.throws(()=>ledger.record({...first,tokens:{...first.tokens,input:999}},job!.id),{code:"USAGE_FACT_CONFLICT"});const afterConflict=ledger.query({taskId:job!.id})[0];assert.deepEqual(afterConflict.tokens,revised.tokens);assert.deepEqual(afterConflict.costs,revised.costs);assert.ok(afterConflict.task.gaps.includes("usage-conflict"));assert.equal(afterConflict.conflicts.length,1);assert.deepEqual(store!.db.prepare("SELECT * FROM requests").all(),budget);
    });
  }
  if(variant === "scheduled")for(const acVariant of ["future","due","duplicate-timer"]){
    acceptance("AC20",acVariant,{level:"E",observer:"native-Pi-command-and-durable-admission",predicate:"one scheduled job starts only after notBefore",artifact:observerArtifact(`schedule-${acVariant}`,{job,scheduleAt,observedQueuedSchedule,requests})},()=>{
      assert.equal(observedQueuedSchedule,true);assert.ok(job!.schedule!.admittedAt!>=scheduleAt);assert.equal(job!.status,"COMPLETED");
      assert.equal(store!.list("managed-jobs").length,1);assert.equal(store!.db.prepare("SELECT count(*) n FROM intents WHERE kind='workspace-create'").get()!.n,1);
      assert.equal(job!.modelSelection!.reason,"manual-selection");assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    });
  }
  if(variant === "opinion-request-timeout"){
    assert.equal(opinionHeld,true);assert.equal(job!.status,"BLOCKED");assert.equal(job!.reason,"REQUEST_TIMEOUT");assert.equal(job!.opinion!.reviews.length,0);
    const expired=store!.events(job!.workScope).filter(event=>event.kind==="request_timeout");assert.equal(expired.length,1);assert.ok(Date.now()-opinionStartedAt<15000);assert.equal(config.executionProfiles.reviewer.timeoutMs,60000);return;
  }
  if(variant === "opinion-quota"){
    acceptance("AC17","B-quota",{level:"E",observer:"real-B-429-and-later-same-model-receiver",predicate:"B waits on shared floor and completes without skipping approval",artifact:observerArtifact(variant,{job,requests,opinionFloor,reviewInputs})},()=>{assert.equal(opinionRejected,true);assert.equal(job!.status,"COMPLETED");assert.equal(job!.opinion!.exchanges,0);assert.equal(job!.opinion!.reviews.at(-1)!.passed,true);assert.equal(writes,1);assert.ok(job!.failures.some(f=>/quota|429/i.test(JSON.stringify(f))));});
  }
  if(variant === "scheduled-explicit"){
    const row=new UsageLedger(store!).query({taskId:job!.id})[0];
    acceptance("AC38","scheduled-explicit-choice",{level:"E",observer:"native-scheduled-command-explicit-model-and-whole-task-ledger",predicate:"schedule uses the selected model and keeps all role costs",artifact:observerArtifact(variant,{job,row,requests,requestedModels,scheduleAt})},()=>{assert.equal(job!.status,"COMPLETED");assert.ok(job!.schedule!.admittedAt!>=scheduleAt);assert.equal(job!.modelSelection!.selected,"backup");assert.equal(job!.routes!.implement,"backup");assert.ok(requestedModels.includes("fixture-backup"));assert.equal(row.task.id,job!.id);assert.ok(row.roles.includes("implement"));assert.ok(row.roles.includes("independent-review"));assert.equal(row.task.resultSource,"verifier");});
  }
  if(variant === "opinion-disagreement-budget"){
    const ledger=new UsageLedger(store!),before=ledger.query({taskId:job!.id})[0],bucket=store!.bucket(`work-${job!.workScope}`),beforeRequests=requests;
    assert.equal(job!.status,"BLOCKED");assert.ok(job!.opinion!.reviews.some(r=>!r.passed));assert.ok(job!.opinion!.exchanges<job!.opinion!.maxExchanges);assert.equal(job!.reason,"BUDGET_DENIED");
    child.stdin.write(JSON.stringify({id:"disagreement-stop",type:"prompt",message:`/orch stop ${job!.id}`})+"\n");const until=Date.now()+10000;while(!protocolEvents.some(e=>e.id==="disagreement-stop")){if(Date.now()>until)throw new Error(output);await delay(20);}job=store!.get<ManagedJob>("managed-jobs",job!.id)!;
    acceptance("AC38","disagreement-budget-stop",{level:"E",observer:"real-A-B-disagreement-budget-denial-and-user-stop",predicate:"budget stops revision and cancellation preserves all spent work",artifact:observerArtifact(variant,{job,before,bucket,requests})},()=>{assert.equal(job!.status,"CANCELLED");assert.equal(requests,beforeRequests);assert.deepEqual(store!.bucket(`work-${job!.workScope}`),bucket);assert.equal(ledger.query({taskId:job!.id})[0].generations,before.generations);assert.ok(before.roles.includes("second-opinion"));assert.ok(before.roles.includes("implement"));assert.notEqual(job!.receipt?.status,"COMPLETED");});return;
  }
  if(variant === "schedule-floor")acceptance("AC20","server-floor",{level:"E",observer:"actual-parent-429-and-scheduled-child-admission",predicate:"scheduled start cannot bypass shared account floor",artifact:observerArtifact(variant,{job,scheduleFloor,observedFloorQueue,requests})},()=>{assert.equal(observedFloorQueue,true);assert.ok(job!.schedule!.admittedAt!>=scheduleFloor);assert.equal(job!.status,"COMPLETED");assert.equal(writes,1);});
  if(variant === "opinion-budget"){
    const bucket=store!.bucket(`work-${job!.workScope}`)!,plan=store!.get<{spec:{required:string[]};steps:Array<{id:string;status:string}>}>("jobs",job!.id)!;
    for(const [ac,name] of [["AC17","budget"],["AC18","reserve-denied"]])acceptance(ac,name,{level:"E",observer:"real-child-request-denial-and-root-reserve",predicate:name,artifact:observerArtifact(name,{job,requests,bucket,plan})},()=>{assert.equal(job!.status,"BLOCKED");assert.notEqual(job!.receipt?.status,"COMPLETED");assert.ok(plan.spec.required.includes("independent-review"));assert.ok(Number(bucket.used)<=7);assert.equal(bucket.reserved,0);assert.ok(job!.failures.some(f=>/BUDGET|budget|reserve/i.test(JSON.stringify(f))));});return;
  }
  if(variant === "schedule-window")acceptance("AC20","window-closes",{level:"E",observer:"native-stream-held-across-real-UTC-window-end",predicate:"task-start window does not terminate active or subsequent steps",artifact:observerArtifact(variant,{job,windowEnd,windowHeld,requests,writes,at:Date.now()})},()=>{assert.equal(windowHeld,true);assert.ok(job!.schedule!.admittedAt!<windowEnd);assert.ok(Date.now()>windowEnd);assert.equal(job!.status,"COMPLETED");assert.equal(writes,1);assert.ok(job!.checks.some(c=>c.checkId==="independent-review"&&c.status==="passed"));});
  if(variant === "opinion-permanent"){
    acceptance("AC17","B-permanent",{level:"E",observer:"real-B-401-and-required-plan",predicate:"permanent B failure blocks rather than accepting A alone",artifact:observerArtifact(variant,{job,requests,reviewRequests})},()=>{assert.equal(opinionRejected,true);assert.equal(job!.status,"BLOCKED");assert.equal(reviewRequests,1);assert.equal(job!.opinion!.reviews.length,0);assert.notEqual(job!.receipt?.status,"COMPLETED");assert.equal(writes,1);});return;
  }
  if(variant === "opinion-cancel"){
    const until=Date.now()+10000;while(!opinionClosed||store!.claims().length){if(Date.now()>until)throw new Error(JSON.stringify({job,claims:store!.claims()}));await delay(20);}job=store!.get<ManagedJob>("managed-jobs",job!.id)!;
    acceptance("AC17","cancel",{level:"E",observer:"actual-B-stream-cancellation-and-reopened-ledger",predicate:"stop revokes B and releases only after physical termination",artifact:observerArtifact(variant,{job,requests,opinionHeld,opinionClosed})},()=>{assert.equal(job!.status,"CANCELLED");assert.equal(opinionHeld,true);assert.equal(opinionClosed,true);assert.equal(job!.opinion!.reviews.length,0);assert.equal(writes,1);assert.equal(store!.claims().length,0);});return;
  }
  if(variant === "opinion-deadline"){
    const until=Date.now()+10000;while(!opinionClosed||store!.claims().length){if(Date.now()>until)throw new Error(JSON.stringify({job,opinionHeld,opinionClosed,claims:store!.claims()}));await delay(20);}
    job=store!.get<ManagedJob>("managed-jobs",job!.id)!;
    acceptance("AC17","deadline",{level:"E",observer:"actual-B-stream-closed-by-task-deadline",predicate:"active B cannot outlive the root deadline or waive acceptance",artifact:observerArtifact("B-deadline",{job,opinionHeld,opinionClosed,requests,writes})},()=>{
      assert.equal(opinionHeld,true);assert.equal(opinionClosed,true);assert.equal(job!.status,"BLOCKED");assert.equal(job!.reason,"task_deadline_exhausted");assert.equal(job!.opinion!.reviews.length,0);assert.equal(writes,1);assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    });return;
  }
  if(variant === "deadline-verifier"){
    const until=Date.now()+10000;while(!deadlineProcess||originalProcessStopped(deadlineProcess)!==true||store!.claims().length){if(Date.now()>until)throw new Error(JSON.stringify({job,deadlineProcess,claims:store!.claims(),output,errors}));await delay(20);}
    job=store!.get<ManagedJob>("managed-jobs",job!.id)!;
    acceptance("AC17","deadline",{level:"E",observer:"actual-verifier-process-and-task-deadline",predicate:"task deadline stops existing work without releasing unknown execution early",artifact:observerArtifact("deadline-verifier",{job,deadlineProcess,requests,effects:readFileSync(join(root,"deadline-effects"),"utf8")})},()=>{
      assert.equal(job!.status,"BLOCKED");assert.equal(job!.reason,"task_deadline_exhausted");assert.equal(job!.deadlineExpired,true);assert.equal(originalProcessStopped(deadlineProcess!),true);assert.equal(requests,0);assert.equal(readFileSync(join(root,"deadline-effects"),"utf8"),"started\n");
    });
    child.stdin.write(JSON.stringify({id:"deadline-resume",type:"prompt",message:`/orch resume ${job.id}`})+"\n");
    while(!protocolEvents.some(event=>event.id==="deadline-resume")){if(Date.now()>until)throw new Error(output);await delay(20);}assert.ok(output.includes("TASK_DEADLINE_EXHAUSTED"));return;
  }
  if(variant === "opinion-unresolved" || variant === "opinion-zero" || variant === "opinion-one"){
    if(variant === "opinion-unresolved"){
      const views=await statusViews(job!.id,"disagreement");acceptance("AC33","unresolved-opinion",{level:"E",observer:"actual-B-disagreement-user-display-and-parent-tool-result",predicate:"remaining findings are visible without claiming agreement",artifact:observerArtifact("opinion-views",views)},()=>{for(const v of [views.ui,views.tool.details,JSON.parse(views.tool.content[0].text)]){assert.equal(v.status,"BLOCKED");assert.equal(v.secondOpinion.agreementCurrent,false);assert.ok(v.secondOpinion.currentFindings.length);}assert.ok(JSON.stringify(views.parentInput).includes("second-view"));});
    }
    if(variant === "opinion-unresolved")acceptance("AC17","unresolved",{level:"E",observer:"final-B-findings-and-blocked-receipt",predicate:"remaining disagreement is reported",artifact:observerArtifact("opinion-unresolved",{job,reviewInputs})},()=>{assert.equal(job!.status,"BLOCKED");assert.ok(job!.opinion!.currentFindings?.length);assert.notEqual(job!.receipt?.status,"COMPLETED");});
    const expected=variant === "opinion-zero"?0:variant === "opinion-one"?1:2,observed={job,requestedModels,requests,reviewInputs};
    acceptance("AC17",variant === "opinion-zero"?"zero-exchange":variant === "opinion-one"?"unresolved":"two-exchanges",{level:"E",observer:"native-A-B-loop-and-shared-ledger",predicate:"configured exchange limit blocks unresolved findings",artifact:observerArtifact(variant,observed)},()=>{
      assert.equal(job!.status,"BLOCKED");assert.equal(job!.reason,"second_opinion_disagreement_exchange_limit");assert.equal(job!.opinion?.exchanges,expected);
      assert.equal(job!.opinion?.reviews.length,expected+1);assert.ok(job!.opinion?.reviews.every(review=>!review.passed));assert.equal(job!.upgradesUsed??0,0);
      assert.equal(job!.semanticAttempts,expected+1);assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    });return;
  }
  const retained=(id:string,name:string,check:()=>void)=>acceptance(id,name,{level:"E",observer:"actual-managed-workflow-receiver-and-receipt",predicate:name,artifact:observerArtifact(`${id}-${name}`,{job,requests,writes,requestedModels,events:protocolEvents})},check);
  const keep:Record<string,Array<[string,string]>>={
    "interrupted-zero":[["AC25","interrupted-zero"]],"silent-build":[["AC25","silent-build"]],"details-only-error":[["AC25","swallowed-error"]],
    "summary-hides-failure":[["AC26","lossy-context"]],"forged-artifact":[["AC26","forged-reference"]],
    "proposal-stale":[["AC26","stale-proposal"]],"premature-review":[["AC26","finish-before-required"]],
  };
  for(const [id,name] of keep[variant]??[])retained(id,name,()=>{
    if(variant === "silent-build"){assert.equal(silentObserved,true);assert.equal(job!.status,"COMPLETED");}
    else{assert.equal(job!.status,"BLOCKED");assert.notEqual(job!.receipt?.status,"COMPLETED");}
    assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    if(variant === "details-only-error")assert.ok(job!.failures.some(f=>f.message.includes("FIXTURE_REQUIRED_DETAILS_ERROR")));
    if(variant === "interrupted-zero")assert.equal(job!.reason,"native_delegation_interrupted");
    if(variant === "forged-artifact")assert.ok(job!.failures.some(f=>f.code==="REVIEW_EVIDENCE_NOT_READ"));
  });
  if(variant === "inspect")retained("AC24","inspect-readonly",()=>{assert.equal(job!.status,"COMPLETED");assert.equal(job!.snapshot,job!.initialSnapshot);assert.equal(JSON.parse(readFileSync(join(job!.cwd!,"answer.json"),"utf8")).answer,1);});
  if(variant === "fix")retained("AC24","fix-success",()=>{assert.equal(job!.status,"COMPLETED");for(const id of ["build","focused-tests","independent-review"])assert.ok(job!.checks.some(check=>check.checkId===id&&check.status==="passed"));});
  if(variant === "repair")retained("AC24","bounded-repair",()=>{assert.equal(job!.status,"COMPLETED");assert.equal(job!.semanticAttempts,2);assert.equal(writes,2);assert.ok(job!.failures.some(failure=>failure.code==="CHECK:focused-tests"&&failure.resolvedBy));});
  if(variant === "unread-review")retained("AC24","required-review-fail",()=>{assert.equal(job!.status,"BLOCKED");assert.notEqual(job!.receipt?.status,"COMPLETED");assert.ok(job!.failures.some(failure=>failure.code.includes("REVIEW_EVIDENCE")));});
  if(variant === "zero-tests")retained("AC24","zero-tests",()=>{assert.equal(job!.status,"BLOCKED");assert.equal(job!.verification["focused-tests"].counts?.tests,0);});
  if(variant === "all-skipped")retained("AC24","all-skip",()=>{assert.equal(job!.status,"BLOCKED");assert.equal(job!.verification["focused-tests"].counts?.skipped,2);assert.equal(job!.verification["focused-tests"].counts?.passed,0);});
  if(variant === "check-input-change")retained("AC24","changed-inputs",()=>{assert.equal(job!.status,"BLOCKED");assert.ok(job!.checkInputChange);});
  if(variant === "optional-failure")retained("AC24","optional-partial",()=>{assert.equal(job!.status,"PARTIAL");assert.deepEqual(job!.receipt?.optionalGaps,["optional-check"]);assert.ok(job!.checks.some(check=>check.checkId==="independent-review"&&check.status==="passed"));});
  if (variant === "verifier-first") assert.fail("Candidate verifier barrier was not reached");
  if(variant === "fallback-budget-exhausted"){
    const initial=structuredClone(job),incidentId=job.recovery!.incidentId;
    const budget=store!.bucket(`incident-${incidentId}`)!,work=store!.bucket(`work-${job.workScope}`)!;
    const grants=store!.list<{jobId:string;routeId:string}>("child-grants").filter(row=>row.value.jobId===job!.id);
    const native=store!.list<{descriptorId:string;process:any;lastResponse:{status:number}}>("child-observations").filter(row=>grants.some(grant=>grant.id===row.value.descriptorId));
    for(const id of ["RTB-010","T28"])evidence(id,()=>{
      assert.deepEqual(budgetLimitCounts,{primary:1,backup:4});assert.equal(budget.used,4);assert.equal(budget.reserved,0);assert.equal(budget.ceiling,4);
      assert.equal(work.used,4);assert.equal(work.reserved,0);assert.equal(grants.length,5);assert.equal(grants.filter(row=>row.value.routeId==="backup").length,4);
      assert.equal(native.length,5);assert.ok(native.every(row=>row.value.lastResponse.status===429&&originalProcessStopped(row.value.process)===true));
      assert.equal(job!.recovery!.stage!.stageId,"primary-tail");assert.equal(job!.recovery!.stage!.deadline,null);assert.equal(job!.status,"WAITING_QUOTA");
      assert.equal(job!.semanticAttempts,1);assert.equal(job!.failures.length,5);assert.equal(writes,0);assert.equal(reviewRequests,0);
      assert.equal(store!.get<{status:string}>("incidents","pool")!.status,"OPEN");assert.ok(store!.get<{notBefore:number}>("incidents","pool")!.notBefore>Date.now());
      assert.equal(store!.db.prepare("SELECT count(*) n FROM requests WHERE state='sent'").get()!.n,4);assert.equal(store!.claims().length,0);
    });
    for(const action of ["pause","resume"]){const id=`budget-${action}`;child.stdin.write(JSON.stringify({id,type:"prompt",message:`/orch ${action} ${job.id}`})+"\n");const until=Date.now()+15000;while(!protocolEvents.some(event=>event.type==="response"&&event.id===id)){if(Date.now()>until)throw new Error(output);await delay(20);}}
    await delay(1200);job=store!.get<ManagedJob>("managed-jobs",job.id)!;
    for(const id of ["RTB-010","T28"])evidence(id,()=>{
      assert.equal(job!.status,"WAITING_QUOTA");assert.deepEqual(job!.recovery!.stage,initial.recovery!.stage);
      assert.equal(store!.list<{jobId:string}>("child-grants").filter(row=>row.value.jobId===job!.id).length,grants.length);
      assert.deepEqual(store!.bucket(`incident-${incidentId}`),budget);assert.deepEqual(store!.bucket(`work-${job!.workScope}`),work);
      assert.deepEqual(budgetLimitCounts,{primary:1,backup:4});assert.equal(job!.semanticAttempts,1);
    });
    statusJobId=job.id;const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:"budget-ui",type:"prompt",message:`/orch status ${job.id}`})+"\n");let until=Date.now()+10000;
    while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id==="budget-ui")){if(Date.now()>until)throw new Error(output);await delay(20);}
    child.stdin.write(JSON.stringify({id:"budget-parent",type:"prompt",message:"Use kernel_task status to explain the retained quota wait"})+"\n");until=Date.now()+15000;
    while(!parentToolResults.some(result=>result.includes("primary-tail"))||!protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    for(const id of ["RTB-010","T28"])evidence(id,()=>{
      for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"WAITING_QUOTA");assert.equal(view.recovery.incidentId,incidentId);assert.equal(view.recovery.stage.stageId,"primary-tail");}
      assert.ok(JSON.stringify(parentInputs.at(-1)).includes(incidentId));assert.deepEqual(budgetLimitCounts,{primary:1,backup:4});
      assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);assert.equal(store!.list("managed-jobs").length,1);
    });
    acceptance("AC29","backup-four",{level:"E",observer:"actual-primary-and-four-backup-429-receiver-results",predicate:"four-attempt cap survives pause/resume without clearing floor or budget",artifact:observerArtifact("backup-four",{job,budget,work,budgetLimitCounts,ui,tool})},()=>{assert.deepEqual(budgetLimitCounts,{primary:1,backup:4});assert.equal(budget.used,4);assert.equal(budget.reserved,0);assert.equal(job!.recovery!.stage!.stageId,"primary-tail");assert.equal(job!.status,"WAITING_QUOTA");});
    acceptance("AC33","waiting-quota",{level:"E",observer:"native-command-UI-and-parent-tool-roundtrip",predicate:"both views retain the same incident and quota wait",artifact:observerArtifact("waiting-quota-views",{ui,tool,parentInput:parentInputs.at(-1)})},()=>{for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"WAITING_QUOTA");assert.equal(view.recovery.incidentId,incidentId);}assert.ok(JSON.stringify(parentInputs.at(-1)).includes(incidentId));});
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"budget-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"four-backup-attempts.json"),JSON.stringify({job,initial,budget,work,grants,native,budgetLimitCounts,ui,tool,parentInput:parentInputs.at(-1)},null,2));}
    return;
  }
  if(variant === "cancel-after-edit"){
    assert.equal(stopped,true);assert.equal(job.status,"CANCELLED");assert.equal(job.reason,"cancelled_termination_confirmed");assert.equal(job.cancelRequested,true);
    assert.equal(candidateConnectionClosed,true);assert.equal(writes,1);assert.equal(requests,2);assert.equal(reviewRequests,0);
    const runtime=JSON.parse(readFileSync(join(state,"artifacts",job.outputs.implement),"utf8"));
    assert.equal(runtime.terminationConfirmed,true);assert.notEqual(runtime.status,"ended");assert.equal(runtime.observations.length,1);
    assert.equal(originalProcessStopped(runtime.observations[0].process),true);
    assert.equal(readFileSync(join(job.cwd!,"answer.json"),"utf8"),'{"answer":2}\n');assert.equal(job.patchArtifact,null);
    assert.notEqual(job.receipt?.status,"COMPLETED");assert.equal(job.verification["focused-tests"],undefined);assert.equal(job.semanticAttempts,1);
    const plan=store!.get<{steps:Array<{id:string;intentId:string;status:string}>}>("jobs",job.id)!,write=plan.steps.find(step=>step.id==="implement")!;
    assert.equal(store!.intent(write.intentId)!.status,"settled");assert.equal(store!.claims().length,0);
    statusJobId=job.id;const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:"cancel-edit-ui",type:"prompt",message:`/orch status ${job.id}`})+"\n");let until=Date.now()+10000;
    while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id==="cancel-edit-ui")){if(Date.now()>until)throw new Error(output);await delay(20);}
    child.stdin.write(JSON.stringify({id:"cancel-edit-parent",type:"prompt",message:"Use kernel_task status to locate the retained partial candidate"})+"\n");until=Date.now()+15000;
    while(!parentToolResults.some(result=>result.includes("CANCELLED"))||!protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"CANCELLED");assert.equal(view.cwd,job.cwd);assert.notEqual(view.receipt?.status,"COMPLETED");}
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes(job.cwd!));assert.ok(JSON.stringify(parentInputs.at(-1)).includes("CANCELLED"));
    assert.equal(writes,1);assert.equal(reviewRequests,0);assert.equal(readFileSync(join(job.cwd!,"answer.json"),"utf8"),'{"answer":2}\n');
    assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"workspace-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"cancel-after-edit.json"),JSON.stringify({runtime,job,ui,tool,parentInput:parentInputs.at(-1),requests,writes,claims:store!.claims()},null,2));}
    return;
  }
  if(variant === "workspace-failure"){
    const operations=readdirSync(join(state,"operations")).filter(name=>name.endsWith(".execution.json")).map(name=>JSON.parse(readFileSync(join(state,"operations",name),"utf8")));
    for(const id of ["WFL-003","T43"])evidence(id,()=>{
      assert.equal(operations.length,1);assert.equal(operations[0].status,"failed");assert.equal(operations[0].exitCode,1);
      assert.equal(operations[0].terminationConfirmed,true);assert.equal(operations[0].terminationCoverage,"pid-namespace");
      assert.match(operations[0].stderr,/EEXIST|ENOTDIR/);assert.equal(job!.status,"BLOCKED");assert.equal(job!.cwd,null);assert.equal(job!.receipt,null);
      assert.match(job!.reason,/EEXIST|ENOTDIR/);assert.equal(requests,0);assert.equal(writes,0);
      assert.equal(store!.get("jobs",job!.id),null);assert.equal(store!.list("child-grants").length,0);
      assert.equal(store!.db.prepare("SELECT count(*) n FROM requests").get()!.n,0);
      assert.equal(readFileSync(join(state,"worktrees"),"utf8"),"preserve obstruction");
    });
    statusJobId=job.id;const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:"workspace-ui",type:"prompt",message:`/orch status ${job.id}`})+"\n");let until=Date.now()+10000;
    while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id==="workspace-ui")){if(Date.now()>until)throw new Error(output);await delay(20);}
    child.stdin.write(JSON.stringify({id:"workspace-parent",type:"prompt",message:"Use kernel_task status to explain the workspace creation failure"})+"\n");until=Date.now()+15000;
    while(!parentToolResults.some(result=>/EEXIST|ENOTDIR/.test(result))||!protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    for(const id of ["WFL-003","T43"])evidence(id,()=>{
      for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"BLOCKED");assert.equal(view.cwd,null);assert.equal(view.receipt,null);assert.match(view.reason,/EEXIST|ENOTDIR/);}
      assert.match(JSON.stringify(parentInputs.at(-1)),/EEXIST|ENOTDIR/);assert.equal(requests,parentRequests);assert.equal(writes,0);
      assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);assert.equal(readFileSync(join(cwd,"user-edit.txt"),"utf8"),"preserved\n");
    });
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"workspace-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"creation-failure.json"),JSON.stringify({operations,job,ui,tool,parentInput:parentInputs.at(-1),requests,claims:store!.claims()},null,2));}
    return;
  }
  if (variant === "spawn-failure") {
    const witness=JSON.parse(readFileSync(join(state,"native-spawn-error.json"),"utf8"));
    const runtime=JSON.parse(readFileSync(join(state,"artifacts",job.outputs.implement),"utf8"));
    assert.equal(witness.attempts.length,1);assert.equal(witness.attempts[0].spawned,false);assert.equal(witness.attempts[0].pid,null);
    assert.equal(witness.attempts[0].error.code,"ENOENT");assert.equal(witness.responses[0].response.status,"failed");
    assert.equal(runtime.nativeStatus,"failed");assert.equal(runtime.nativeExitCode,1);assert.match(runtime.error,/ENOENT/);
    assert.equal(runtime.descriptorId,witness.responses[0].response.requestId);assert.equal(runtime.nativeRunId,witness.responses[0].response.runId);
    assert.equal(runtime.observations.length,0);assert.equal(runtime.status,"unknown");assert.equal(runtime.terminationConfirmed,false);
    assert.equal(job.status,"BLOCKED");assert.equal(job.receipt!.status,"BLOCKED");assert.equal(requests,0);assert.equal(writes,0);assert.equal(reviewRequests,0);
    assert.ok(job.receipt!.failureHistory.some(failure=>failure.message.includes("ENOENT")));
    assert.ok(job.receipt!.reasons.includes("unknown_mutator"));
    statusJobId=job.id;const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:"spawn-ui",type:"prompt",message:`/orch status ${job.id}`})+"\n");let until=Date.now()+10000;
    while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id==="spawn-ui")){if(Date.now()>until)throw new Error(output);await delay(20);}
    child.stdin.write(JSON.stringify({id:"spawn-parent",type:"prompt",message:"Use kernel_task status to explain why the child did not start"})+"\n");until=Date.now()+15000;
    while(!parentToolResults.some(result=>result.includes("ENOENT"))||!protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id&&value.receipt);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"BLOCKED");assert.equal(view.receipt.status,"BLOCKED");assert.ok(JSON.stringify(view.failureGroups).includes("ENOENT"));}
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("ENOENT"));assert.equal(requests,parentRequests);assert.equal(writes,0);
    const plan=store!.get<{steps:Array<{id:string;status:string;intentId:string}>}>("jobs",job.id)!;
    const implementation=plan.steps.find(step=>step.id==="implement")!;assert.equal(implementation.status,"unknown");assert.equal(store!.intent(implementation.intentId)!.status,"unknown");
    assert.ok(store!.claims().some(claim=>claim.intent_id===implementation.intentId));assert.equal(store!.list("child-observations").length,0);
    assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"native-start-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"workflow-spawn-failure.json"),JSON.stringify({witness,runtime,job,ui,tool,parentInput:parentInputs.at(-1),requests,claims:store!.claims()},null,2));}
    return;
  }
  if (variant === "baseline-environment-failure") {
    assert.equal(diagnosisRequests, 0); assert.equal(store!.get<{semanticReplans?:number}>("jobs", job.id)?.semanticReplans ?? 0, 0);
    const result = job.verification["baseline:build"], originalRequests = requests;
    assert.equal(result.failureCategory, "environment"); assert.equal(result.status, "failed");
    assert.equal(result.terminationConfirmed, true); assert.equal(result.terminationCoverage, "pid-namespace");
    assert.equal(result.exitCode, 1); assert.equal(result.notSent, false);
    assert.equal(job.status, "BLOCKED"); assert.equal(job.reason, "baseline_environment_failed");
    assert.equal(job.semanticAttempts, 1); // Initial allocated attempt; no repair or upgrade consumed. assert.equal(job.upgradesUsed ?? 0, 0);
    assert.equal(job.receipt!.status, "BLOCKED"); assert.equal(writes, 0); assert.equal(originalRequests, 0);
    const plan = store!.get<{dispatched:number; steps:Array<{id:string;status:string;intentId:string|null}>}>("jobs",job.id)!;
    assert.equal(plan.dispatched, 1); assert.equal(plan.steps.find(step => step.id === "implement")!.status, "pending");
    assert.equal(plan.steps.find(step => step.id === "implement")!.intentId, null);
    assert.equal(store!.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0);
    statusJobId = job.id; const offset = protocolEvents.length;
    child.stdin.write(JSON.stringify({id:"baseline-ui", type:"prompt", message:`/orch status ${job.id}`})+"\n");
    let until = Date.now()+10000;
    while(!protocolEvents.slice(offset).some(event => event.type === "response" && event.id === "baseline-ui")) { if(Date.now()>until)throw new Error(output);await delay(20); }
    child.stdin.write(JSON.stringify({id:"baseline-parent", type:"prompt", message:"Use kernel_task status to explain the blocked baseline"})+"\n");
    until=Date.now()+15000;
    while(!parentToolResults.some(value=>value.includes("baseline_environment_failed")) || !protocolEvents.some(event=>event.type==="tool_execution_end" && event.toolName==="kernel_task")) { if(Date.now()>until)throw new Error(output);await delay(20); }
    const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request" && event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id && value.receipt);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end" && event.toolName==="kernel_task").at(-1)!.result;
    for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]) {
      assert.equal(view.status,"BLOCKED");assert.equal(view.reason,"baseline_environment_failed");assert.equal(view.receipt.status,"BLOCKED");
      assert.ok(view.failureGroups.some((failure:{code:string;unresolved:number})=>failure.code==="CHECK:build" && failure.unresolved>0));
    }
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("CHECK:build"));
    assert.equal(writes,0);assert.equal(reviewRequests,0);assert.equal(criticRequests,0);assert.equal(requests,parentRequests);
    assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"receipt-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"baseline-environment.json"),JSON.stringify({result,job,plan,ui,tool,parentInput:parentInputs.at(-1),requests,parentRequests,writes},null,2));}
    return;
  }
  if (variant === "interrupted-zero") {
    const witness=JSON.parse(readFileSync(join(state,"interrupted-zero.json"),"utf8")),runtime=JSON.parse(readFileSync(join(state,"artifacts",job.outputs.implement),"utf8"));
    for(const id of ["EXE-006","T02"]) evidence(id,()=>{
      assert.equal(witness.nativeBefore.status,"completed");assert.equal(witness.bridge.details.results[0].exitCode,0);assert.equal(witness.bridge.details.results[0].interrupted,true);
      assert.equal(witness.converted.status,"interrupted");assert.equal(runtime.status,"failed");assert.equal(runtime.terminationConfirmed,true);
      assert.equal(runtime.nativeStatus,"interrupted");assert.equal(runtime.nativeExitCode,0);assert.equal(runtime.error,"native_delegation_interrupted");
      assert.equal(job!.status,"BLOCKED");assert.equal(job!.receipt!.status,"BLOCKED");assert.equal(job!.reason,"native_delegation_interrupted");
      assert.ok(job!.receipt!.failureHistory.some(failure=>failure.message.includes("native_delegation_interrupted")));
      assert.equal(writes,1);assert.equal(reviewRequests,0);assert.equal(job!.verification["focused-tests"],undefined);assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    });
    statusJobId=job.id;const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id:"interrupted-ui",type:"prompt",message:`/orch status ${job.id}`})+"\n");let until=Date.now()+10000;
    while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id==="interrupted-ui")){if(Date.now()>until)throw new Error(output);await delay(20);}
    child.stdin.write(JSON.stringify({id:"interrupted-parent",type:"prompt",message:"Use kernel_task status to explain why the task is blocked"})+"\n");until=Date.now()+15000;
    while(!parentToolResults.some(result=>result.includes("native_delegation_interrupted"))||!protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id&&value.receipt);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    for(const id of ["EXE-006","T02"]) evidence(id,()=>{
      for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"BLOCKED");assert.equal(view.receipt.status,"BLOCKED");assert.ok(view.failureGroups.some((failure:{sample:string})=>failure.sample.includes("native_delegation_interrupted")));}
      assert.ok(JSON.stringify(parentInputs.at(-1)).includes("native_delegation_interrupted"));assert.equal(writes,1);assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    });
    acceptance("AC33","blocked-acceptance",{level:"E",observer:"native-interrupted-result-and-user-parent-projections",predicate:"exit zero cannot hide interrupted required execution",artifact:observerArtifact("blocked-views",{ui,tool,parentInput:parentInputs.at(-1),witness})},()=>{for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"BLOCKED");assert.equal(view.receipt.status,"BLOCKED");}assert.ok(JSON.stringify(parentInputs.at(-1)).includes("native_delegation_interrupted"));});
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"execution-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"interrupted-zero.json"),JSON.stringify({witness,runtime,job,ui,tool,parentInput:parentInputs.at(-1)},null,2));}
    return;
  }
  if (variant === "check-threshold-change") {
    assert.equal(job.status,"BLOCKED"); assert.equal(job.reason,"ACCEPTANCE_INPUTS_CHANGED_REQUIRE_APPROVAL"); assert.ok(job.checkInputChange);
    const candidate = JSON.parse(readFileSync(join(job.cwd!,"answer.json"),"utf8")), weakened = JSON.parse(readFileSync(join(job.cwd!,"checks.json"),"utf8"));
    assert.equal(candidate.answer,0); assert.equal(weakened.expected,0); assert.ok(candidate.answer >= weakened.expected); assert.ok(candidate.answer < 2);
    assert.equal(job.verification.build,undefined); assert.equal(job.verification["focused-tests"],undefined); assert.equal(reviewRequests,0);
    assert.equal(job.receipt!.status,"BLOCKED"); assert.equal(job.receipt!.specVersion,1); assert.notEqual(job.checkInputChange!.digest,job.checkInputsDigest);
    assert.equal(readFileSync(join(cwd,"checks.json"),"utf8"),'{"expected":2}\n'); assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');
    statusJobId=job.id; const beforeQuery=requests;
    child.stdin.write(JSON.stringify({id:"threshold-ui",type:"prompt",message:`/orch status ${job.id}`})+"\n");
    let until=Date.now()+10000;
    while(!protocolEvents.some(event=>event.type==="response"&&event.id==="threshold-ui")){if(Date.now()>until)throw new Error(output);await delay(20);}
    child.stdin.write(JSON.stringify({id:"threshold-tool",type:"prompt",message:"Use kernel_task status to explain the required check approval"})+"\n");until=Date.now()+15000;
    while(!parentToolResults.some(result=>result.includes("ACCEPTANCE_INPUTS_CHANGED_REQUIRE_APPROVAL")) || !protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const ui=protocolEvents.filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).filter(value=>value.id===job!.id&&value.receipt).at(-1);
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    for(const view of [ui,tool.details,JSON.parse(tool.content[0].text)]){assert.equal(view.status,"BLOCKED");assert.equal(view.checkInputChange.digest,job.checkInputChange!.digest);assert.equal(view.receipt.specVersion,1);}
    assert.equal(requests-beforeQuery,2);assert.equal(writes,1);assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("ACCEPTANCE_INPUTS_CHANGED_REQUIRE_APPROVAL"));
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"receipt-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"threshold-change.json"),JSON.stringify({job,candidate,weakened,ui,tool,parentInput:parentInputs.at(-1),writes,requests},null,2));}
    return;
  }
  if (variant === "budget-local-verification") {
    assert.ok(job); assert.equal(job.status, "BLOCKED"); assert.equal(job.receipt!.status, "BLOCKED"); assert.equal(writes, 1);
    for (const id of ["build", "focused-tests"]) { assert.equal(job.verification[id].status, "passed"); assert.equal(job.verification[id].terminationConfirmed, true); }
    assert.equal(job.verification["focused-tests"].counts!.tests, 1); assert.equal(job.verification["focused-tests"].counts!.passed, 1);
    assert.equal(requests, 2); assert.equal(reviewRequests, 0); assert.equal(store!.bucket(`work-${job.workScope}`)!.used, 2); assert.equal(store!.bucket(`work-${job.workScope}`)!.reserved, 0);
    assert.ok(job.receipt!.reasons.includes("required:independent-review")); assert.equal(job.semanticAttempts, 1);
    const review = JSON.parse(readFileSync(join(state, "artifacts", job.outputs["independent-review"]), "utf8"));
    assert.ok(review.observations.some((item: {requestDenials: string[]}) => item.requestDenials.includes("BUDGET_DENIED")));
    assert.equal(readFileSync(join(job.cwd!, "answer.json"), "utf8"), '{"answer":2}\n'); assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
    assert.equal(git("status", "--porcelain=v1"), before); return;
  }
  if (variant === "proposal-stale") {
    const associated = store!.list<{contract: {jobId: string}}>("proposal-executions");
    for (const id of ["EVD-007", "T59"]) evidence(id, () => {
      assert.equal(job!.status, "BLOCKED"); assert.match(job!.reason, /CANDIDATE_CHANGED_BEFORE_CHECK|STALE_PROPOSAL/); assert.equal(requests, 0); assert.equal(writes, 0);
      assert.equal(associated.length, 1); assert.equal(associated[0].value.contract.jobId, job!.id); assert.equal(store!.intent(associated[0].id)!.status, "not_sent");
      assert.equal(readFileSync(join(job!.cwd!, "answer.json"), "utf8"), '{"answer":3}\n'); assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      assert.equal(existsSync(join(sharedRoot, "checks.txt")), false);
    });
    const rejected = structuredClone(job), rejectedRequests = requests;
    child.stdin.write(JSON.stringify({ type: "prompt", id: "resume-stale-candidate", message: `/orch resume ${job.id}` }) + "\n");
    const resumeDeadline = Date.now() + 30000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "resume-stale-candidate")) { if (Date.now() > resumeDeadline) throw new Error(output); await delay(20); }
    while ((job = store!.get<ManagedJob>("managed-jobs", job.id)!).status !== "COMPLETED") {
      if (Date.now() > resumeDeadline || job.status === "BLOCKED") throw new Error(JSON.stringify({ job, output, errors })); await delay(20);
    }
    for (const id of ["EVD-007", "T59"]) evidence(id, () => {
      assert.equal(job!.status, "COMPLETED"); assert.equal(store!.intent(associated[0].id)!.status, "not_sent");
      assert.equal(store!.list("proposal-executions").length, 1); assert.equal(writes, 1);
      assert.equal(readFileSync(join(job!.cwd!, "answer.json"), "utf8"), '{"answer":2}\n'); assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs);
    });
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "proposal-observers"); mkdirSync(path, {recursive:true});
      writeFileSync(join(path, "stale.json"), JSON.stringify({ rejected, rejectedRequests, resumed: job, associated, proposalWitness, requests, writes }, null, 2)); }
    return;
  }
  if (variant === "shared-directory-drift") {
    assert.equal(sharedRetargeted, true); assert.equal(job.status, "BLOCKED"); assert.match(job.reason, /SHARED_DIRECTORY_BINDING_CHANGED/);
    assert.equal(requests, 0); assert.equal(writes, 0); assert.equal(readFileSync(join(sharedRoot, "checks.txt"), "utf8"), "check\n");
    assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs);
    assert.equal(existsSync(join(root, "different-shared-root/checks.txt")), false);
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "shared-resource-observers"); mkdirSync(path, {recursive:true});
      writeFileSync(join(path, "drift.json"), JSON.stringify({ job, sharedRetargeted, requests, writes, claims: store!.claims() }, null, 2)); }
    return;
  }
  if (variant.startsWith("cancel-verifier")) {
    // CANCELLED is persisted before the separate job-lease release. Observe
    // completion of both facts; do not treat the first database write as a barrier.
    const releaseDeadline = Date.now() + 10000;
    while (store!.claims().length > 0) {
      if (Date.now() > releaseDeadline) throw new Error(JSON.stringify({ phase: "cancelled verifier resource release", claims: store!.claims(), job }));
      await delay(20);
    }
    job = store!.get<ManagedJob>("managed-jobs", job!.id)!;
    matrixCase("await-orders", `R10.stop.${variant === "cancel-verifier-first" ? "revoke-first" : "await-first"}`, () => {
      assert.equal(stopped, true); assert.equal(job!.status, "CANCELLED", JSON.stringify(job)); assert.equal(job!.cancelRequested, true);
      assert.equal(job!.receipt?.status === "COMPLETED", false); assert.equal(reviewRequests, 0); assert.equal(writes, 1);
      assert.equal(existsSync(join(root, "verifier-completed")), variant === "cancel-verifier-late");
      assert.equal(job!.verification["focused-tests"].terminationConfirmed, true);
      assert.equal(job!.verification["focused-tests"].status, variant === "cancel-verifier-first" ? "failed" : "passed");
      assert.equal(store!.get<{steps:Array<{id:string;status:string}>}>("jobs", job!.id)!.steps.find(step => step.id === "focused-tests")!.status, "failed");
      assert.equal(store!.claims().length, 0); assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      assert.equal(JSON.parse(readFileSync(join(job!.cwd!, "answer.json"), "utf8")).answer, 2);
    }); return;
  }
  if (["zero-tests", "worker-claim", "step-cap", "details-only-error", "forged-artifact", "summary-hides-failure", "all-skipped", "unknown-tests", "unread-review", "premature-review", "stripped-review-input", "mutating-check", "cancel", "check-input-change", "environment-failure", "network-exhausted"].includes(variant)) {
    assert.notEqual(job.status, "COMPLETED", JSON.stringify(job));
    assert.equal(job.receipt?.status === "COMPLETED", false);
    assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
    if (!["unread-review", "forged-artifact", "premature-review", "stripped-review-input"].includes(variant)) assert.equal(reviewRequests, 0);
    if (variant === "worker-claim") {
      const claim = JSON.parse(readFileSync(join(job.cwd!, "claimed-verification.json"), "utf8"));
      assert.equal(claim.passed, 99); assert.equal(job.status, "BLOCKED"); assert.equal(job.receipt!.status, "BLOCKED");
      assert.equal(job.verification["focused-tests"].status, "failed"); assert.equal(job.verification["focused-tests"].counts!.passed, 0);
      assert.ok(job.receipt!.reasons.includes("required:focused-tests")); assert.equal(reviewRequests, 0); assert.equal(writes, 3);
      assert.equal(job.semanticAttempts, 3); assert.equal(JSON.parse(readFileSync(join(job.cwd!, "answer.json"), "utf8")).answer, 1);
      assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
    }
    if (variant === "step-cap") {
      acceptance("AC30","many-rounds",{level:"E",observer:"native-workflow-and-receiver",predicate:"step limit cannot upgrade model or reset task",artifact:observerArtifact("no-cascade-step-cap",{job,requestedModels,requests})},()=>{
        assert.equal(job.upgradesUsed??0,0);assert.equal(job.status,"BLOCKED");assert.equal(requestedModels.includes("fixture-backup"),false);assert.equal(store!.list("managed-jobs").length,1);
      });
      assert.equal(job.status, "BLOCKED"); assert.equal(job.reason, "step_budget_exhausted"); assert.equal(job.semanticAttempts, 2); assert.equal(writes, 2);
      assert.equal(store!.get<{dispatched:number}>("jobs", job.id)!.dispatched, 5); assert.equal(JSON.parse(readFileSync(join(job.cwd!, "answer.json"), "utf8")).answer, 2);
      child.stdin.write(JSON.stringify({ id: "resume-exhausted", type: "prompt", message: `/orch resume ${job.id}` }) + "\n");
      const until = Date.now() + 10000;
      while (!protocolEvents.some(event => event.type === "response" && event.id === "resume-exhausted")) { if (Date.now() > until) throw new Error(output); await delay(20); }
      await delay(100);
      for (const id of ["WFL-007", "T72"]) evidence(id, () => {
        assert.equal(store!.get<ManagedJob>("managed-jobs", job!.id)!.status, "BLOCKED");
        assert.equal(store!.get<{dispatched:number}>("jobs", job!.id)!.dispatched, 5); assert.equal(writes, 2);
        assert.ok(output.includes("STEP_BUDGET_EXHAUSTED")); assert.equal(store!.list("managed-jobs").length, 1);
        assert.equal(job!.receipt!.status, "BLOCKED"); assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      }); return;
    }
    if (variant === "summary-hides-failure") {
      const originalFailure = job.failures.find(failure => failure.code === "CHECK:focused-tests")!, receiptId = job.outputs.receipt;
      const prompt = async (id: string, message: string) => {
        const offset = protocolEvents.length; child.stdin.write(JSON.stringify({ id, type: "prompt", message }) + "\n");
        const until = Date.now() + 15000;
        while (!protocolEvents.slice(offset).some(event => event.type === "agent_settled")) {
          if (Date.now() > until) throw new Error(JSON.stringify({ output, errors })); await delay(20);
        }
      };
      await prompt("before-summary", "Give a brief status summary. " + "Context filler. ".repeat(4000));
      child.stdin.write(JSON.stringify({ id: "lossy-compact", type: "compact", customInstructions: "Fixture summarizer deliberately omits old failure details." }) + "\n");
      let until = Date.now() + 15000;
      while (!protocolEvents.some(event => event.type === "response" && event.id === "lossy-compact")) {
        if (Date.now() > until) throw new Error(JSON.stringify({ output, errors })); await delay(20);
      }
      const compacted = protocolEvents.find(event => event.type === "response" && event.id === "lossy-compact")!;
      assert.equal(compacted.success, true, JSON.stringify(compacted));
      await prompt("after-summary", "What remains unverified for this job?");
      child.stdin.write(JSON.stringify({ id: "summary-status", type: "prompt", message: `/orch status ${job.id}` }) + "\n"); until = Date.now() + 10000;
      while (!protocolEvents.some(event => event.type === "response" && event.id === "summary-status")) {
        if (Date.now() > until) throw new Error(output); await delay(20);
      }
      const ui = protocolEvents.filter(event => event.type === "extension_ui_request" && event.method === "notify")
        .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).filter(value => value.id === job!.id && value.receipt).at(-1);
      const after = JSON.stringify(parentInputs.at(-1));
      const records = process.env.TASK_KEEPER_TEST_RECORD_DIR;
      if (records) {
        const path = join(dirname(records), "context-observers"); mkdirSync(path, { recursive: true });
        writeFileSync(join(path, `${job.id}.json`), JSON.stringify({ variant, jobId: job.id, receiptId, failure: originalFailure, parentInputs,
          summary: compacted.data, ui, summaryRequests, requests, writes, reviewRequests }), { mode: 0o600 });
      }
      for (const id of ["EVD-004", "T11", "T53", "T57"]) evidence(id, () => {
        assert.ok(summaryRequests > 0); assert.equal(compacted.data.summary.includes(originalFailure.id), false);
        assert.equal(parentRequests, 2); assert.ok(after.includes(originalFailure.id)); assert.ok(after.includes("CHECK:focused-tests"));
        assert.ok(after.includes(receiptId)); assert.ok(after.includes("BLOCKED")); assert.ok(after.includes("unresolvedIds"));
        assert.equal(ui.receipt.status, "BLOCKED"); assert.ok(ui.failureGroups.some((group: {code:string;unresolved:number}) => group.code === "CHECK:focused-tests" && group.unresolved === 1));
        assert.equal(store!.get<ManagedJob>("managed-jobs", job!.id)!.receipt!.status, "BLOCKED"); assert.equal(writes, 1); assert.equal(reviewRequests, 0);
        assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      }); return;
    }
    if (["zero-tests", "worker-claim", "details-only-error", "forged-artifact", "premature-review", "stripped-review-input", "all-skipped", "unknown-tests"].includes(variant)) {
      statusJobId = job.id;
      const beforeStatus = requests;
      child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch status ${job.id}`, id: "failure-status-ui" }) + "\n");
      const uiDeadline = Date.now() + 15000;
      while (!protocolEvents.some(event => event.type === "response" && event.id === "failure-status-ui")) {
        if (Date.now() > uiDeadline) throw new Error(JSON.stringify({ output, errors })); await delay(20);
      }
      child.stdin.write(JSON.stringify({ type: "prompt", message: "Read the existing job's status using kernel_task; report its required check evidence", id: "failure-status-model" }) + "\n");
      const until = Date.now() + 15000;
      while (!parentToolResults.some(result => result.includes(job!.id) && result.includes("BLOCKED"))) {
        if (Date.now() > until) throw new Error(JSON.stringify({ output, errors, parentToolResults })); await delay(20);
      }
      const events = protocolEvents;
      const ui = events.filter(event => event.type === "extension_ui_request" && event.method === "notify")
        .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).find(value => value.id === job!.id && value.receipt);
      const tool = events.find(event => event.type === "tool_execution_end" && event.toolName === "kernel_task" && event.result?.details?.id === job!.id);
      const expectedReason = variant === "worker-claim" ? "nonzero_exit" : ["premature-review", "stripped-review-input"].includes(variant) ? "REVIEW_EVIDENCE_NOT_DELIVERED" : variant === "forged-artifact" ? "REVIEW_EVIDENCE_NOT_READ" : variant === "details-only-error" ? "FIXTURE_REQUIRED_DETAILS_ERROR" : variant === "unknown-tests" ? "test_count_unknown" : "required_tests_not_passed";
      for (const id of coverageIds[variant].split(" ")) evidence(id, () => {
        if (variant === "premature-review" || variant === "stripped-review-input") {
          const runtime = JSON.parse(readFileSync(join(state, "artifacts", job!.outputs["independent-review"]), "utf8"));
          assert.equal(runtime.content.value.verdict, "pass"); assert.equal(runtime.status, "ended");
          const observation = runtime.observations[0], verdict = observation.structuredOutputs[0];
          assert.ok(observation.fileReads.length > 0); assert.ok(observation.artifactReads.length > 0);
          for (const read of [...observation.fileReads, ...observation.artifactReads]) {
            if (variant === "premature-review") assert.equal(read.readRequest, verdict.requestOrdinal);
            else assert.ok(read.readRequest < verdict.requestOrdinal);
            assert.ok(read.deliveredRequest === undefined || read.deliveredRequest > verdict.requestOrdinal);
          }
          assert.equal(job!.receipt!.status, "BLOCKED"); assert.equal(job!.reason, expectedReason);
          if (id === "T03") {
            assert.equal(runtime.terminationConfirmed, true); assert.equal(job!.verification.build.status, "passed");
            assert.equal(job!.verification["focused-tests"].status, "passed"); assert.ok(job!.receipt!.reasons.includes("required:independent-review"));
            assert.ok(job!.receipt!.failureHistory.some(failure => failure.message.includes("REVIEW_EVIDENCE_NOT_DELIVERED")));
          }
          if (variant === "stripped-review-input") {
            assert.ok(JSON.stringify(reviewInputs).includes("Tool output omitted before transport")); assert.ok(existsSync(join(root, "review-input-control.json")));
          }
        } else if (variant === "forged-artifact") {
          assert.ok(foreignArtifact); assert.equal(store!.get<{jobId:string}>("artifacts", foreignArtifact)!.jobId, "foreign-job");
          assert.ok(JSON.stringify(reviewInputs).includes("ARTIFACT_NOT_ATTACHED_TO_STEP")); assert.equal(JSON.stringify(reviewInputs).includes("FOREIGN_PRIVATE_SENTINEL"), false);
          assert.ok(job!.failures.some(failure => failure.message.includes("ARTIFACT_NOT_ATTACHED_TO_STEP")));
          assert.equal(job!.verification["focused-tests"].status, "passed"); assert.equal(job!.receipt!.status, "BLOCKED");
        } else if (variant === "details-only-error") {
          const witness = JSON.parse(readFileSync(join(state, "details-only-error.json"), "utf8"));
          const runtime = JSON.parse(readFileSync(join(state, "artifacts", job!.outputs.implement), "utf8"));
          assert.equal(witness.bridge.content[0].text, "Done"); assert.equal(witness.bridge.details.results[0].error, expectedReason);
          assert.equal(witness.converted.status, "failed"); assert.equal(runtime.status, "failed"); assert.equal(runtime.error, expectedReason);
          assert.equal(runtime.terminationConfirmed, true); assert.ok(job!.receipt!.failureHistory.some(failure => failure.message.includes(expectedReason)));
        } else {
        assert.equal(job!.status, "BLOCKED"); assert.equal(job!.verification["focused-tests"].exitCode, variant === "worker-claim" ? 1 : 0);
        assert.equal(job!.verification["focused-tests"].reason, expectedReason); assert.equal(job!.verification["focused-tests"].terminationConfirmed, true);
        assert.equal(job!.verification["focused-tests"].status, variant === "unknown-tests" ? "unknown" : "failed");
        assert.ok(job!.failures.some(failure => failure.required && failure.code === "CHECK:focused-tests"));
        }
        assert.equal(ui?.status, "BLOCKED"); assert.equal(ui?.receipt.status, "BLOCKED");
        assert.equal(tool?.result.details.status, "BLOCKED");
        assert.deepEqual(JSON.parse(tool.result.content[0].text), tool.result.details);
        assert.ok(parentToolResults.some(result => result.includes(expectedReason) && result.includes(job!.id)));
        assert.equal(requests - beforeStatus, 2); if (["forged-artifact", "premature-review", "stripped-review-input"].includes(variant)) assert.ok(reviewRequests >= 1); else assert.equal(reviewRequests, 0); assert.equal(writes, variant === "worker-claim" ? 3 : 1);
        assert.equal(store!.list("managed-jobs").length, 1); assert.equal(git("status", "--porcelain=v1"), before);
      });
    }
    if (variant === "premature-review") {
      let until = Date.now() + 10000;
      const toolAt = protocolEvents.findLastIndex(event => event.type === "tool_execution_end" && event.toolName === "kernel_task");
      while (!protocolEvents.slice(toolAt).some(event => event.type === "agent_settled")) { if (Date.now() > until) throw new Error(output); await delay(20); }
      const gateFailure = job.failures.find(failure => failure.code === "REVIEW_EVIDENCE_NOT_DELIVERED")!;
      assert.ok(gateFailure); assert.equal(gateFailure.required, true); assert.equal(gateFailure.resolvedBy, null);
      acceptReviewRetry = true; child.stdin.write(JSON.stringify({id:"retry-valid-review",type:"prompt",message:`/orch resume ${job.id}`}) + "\n");
      until = Date.now() + 30000;
      while (store!.get<ManagedJob>("managed-jobs",job.id)!.status !== "COMPLETED") {
        if (Date.now() > until) throw new Error(JSON.stringify({job:store!.get("managed-jobs",job.id),output,errors})); await delay(20);
      }
      const recovered = store!.get<ManagedJob>("managed-jobs",job.id)!;
      for (const id of ["WFL-009", "T03"]) evidence(id, () => {
        assert.equal(recovered.receipt!.status, "COMPLETED"); assert.equal(writes, 1); assert.equal(recovered.semanticAttempts, 1);
        const retained = recovered.receipt!.failureHistory.find(failure => failure.id === gateFailure.id)!;
        assert.equal(retained.code, gateFailure.code); assert.equal(retained.attemptId, gateFailure.attemptId); assert.ok(retained.resolvedBy);
        assert.ok(recovered.checks.some(check => check.checkId === "independent-review" && check.status === "passed" && check.artifactId === retained.resolvedBy));
        assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"), '{"answer":1}\n');
      });
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"receipt-observers"); mkdirSync(path,{recursive:true});
        writeFileSync(join(path,"review-gate-recovery.json"),JSON.stringify({blocked:job,recovered,gateFailure,writes,reviewRequests},null,2));
      }
    }
    if(variant === "environment-failure")acceptance("AC30","environment-fail",{level:"E",observer:"native-workflow-and-receiver",predicate:"real failed check retains bounded original model",artifact:observerArtifact(`no-cascade-${variant}`,{job,requestedModels,requests})},()=>{
      assert.equal(job.upgradesUsed??0,0);assert.ok(job.status!=="COMPLETED");assert.equal(requestedModels.includes("fixture-backup"),false);assert.ok(job.receipt?.reasons.length);
    });
    if (variant === "environment-failure") { assert.equal(job.semanticAttempts, 1); assert.equal(job.upgradesUsed ?? 0, 0); assert.equal(diagnosisRequests, 0); assert.equal(store!.get<{semanticReplans?:number}>("jobs", job.id)?.semanticReplans ?? 0, 0); }
    if (variant === "check-input-change") { assert.ok(job.checkInputChange); assert.equal(job.verification.build, undefined); }
    if (variant === "cancel") assert.equal(job.cancelRequested, true);
    if (variant === "network-exhausted") {
      assert.equal(job.reason, "network_attempts_exhausted"); assert.equal(requests, 3); assert.equal(job.semanticAttempts, 1);
      assert.equal(job.recovery?.networkAttempts, 3); assert.equal(store!.list("incidents").length, 0);
      assert.ok(store!.list("transport-incidents").length);
    }
    return;
  }
  if (variant === "optional-failure" || variant === "optional-disallowed") {
    assert.equal(job.status, variant === "optional-failure" ? "PARTIAL" : "BLOCKED", JSON.stringify(job));
    assert.deepEqual(job.receipt?.optionalGaps, ["optional-check"]);
    assert.ok(job.checks.some(check => check.checkId === "independent-review" && check.status === "passed"));
    assert.ok(job.failures.some(failure => failure.code === "CHECK:optional-check" && !failure.required));
    assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n'); assert.equal(git("show-ref"), refs);
    return;
  }
  if(variant === "premature-critic"){
    retained("AC18","incomplete-B",()=>{assert.equal(job!.status,"BLOCKED");assert.equal(job!.outputs.reviewReuse,undefined);assert.ok(job!.failures.some(f=>f.code==="REVIEW_EVIDENCE_NOT_DELIVERED"));});
    const failure=job.failures.find(failure=>failure.code==="REVIEW_EVIDENCE_NOT_DELIVERED")!;
    assert.ok(failure);assert.equal(failure.required,true);assert.equal(job.status,"BLOCKED");assert.notEqual(job.receipt?.status,"COMPLETED");assert.equal(writes,1);
    assert.equal(store!.get<{steps:Array<{id:string;status:string}>}>("jobs",job.id)!.steps.find(step=>step.id==="second-opinion")!.status,"failed");return;
  }
  if (variant === "review-reuse") {
    retained("AC18","valid-B-reuse",()=>{assert.ok(job!.outputs.reviewReuse);assert.equal(reviewRequests,criticRequests);assert.equal(job!.opinion!.reviews.at(-1)!.snapshot,job!.snapshot);assert.equal(job!.receipt!.status,"COMPLETED");});
    assert.ok(job.outputs.reviewReuse, JSON.stringify(job)); assert.equal(reviewRequests, criticRequests); assert.ok(criticRequests >= 2);
    assert.equal(job.critiquesUsed, 1); assert.equal(job.semanticAttempts, 1);
  }
  if (variant === "binding-approval") {
    assert.equal(bindingRefreshed, true); assert.equal(bindingApproved, true); assert.equal(bindingResumed, true);
    assert.equal(job.receipt?.specVersion, 2); assert.ok(job.outputs.bindingApproval); assert.equal(job.semanticAttempts, 1);
  }
  if (variant === "repair") {
    assert.equal(job.semanticAttempts, 2, JSON.stringify(job)); assert.ok(job.failures.some((failure) => failure.code === "CHECK:focused-tests" && failure.resolvedBy));
    assert.equal(writes, 2);
  }
  assert.equal(job.status, "COMPLETED", JSON.stringify({ job, requests, output, errors }));
  if(variant === "silent-build") {
    for(const id of ["EXE-013","T16"]) evidence(id,()=>{assert.equal(silentObserved,true);assert.equal(job!.status,"COMPLETED");assert.equal(job!.receipt!.status,"COMPLETED");
      for(const key of ["baseline:build","build"]){const result:VerificationResult=job!.verification[key];assert.equal(result.status,"passed");assert.equal(result.stdout,"");assert.equal(result.terminationConfirmed,true);assert.equal(result.reason,"verified");}
      assert.equal(writes,1);assert.equal(job!.semanticAttempts,1);assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');});
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"verification-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"silent-build.json"),JSON.stringify({silentWitness,job,requests,writes},null,2));}
  }
  if (variant === "terminal-resume") {
    const originalJob = store!.get("managed-jobs", job.id), originalPlan = store!.get("jobs", job.id), originalBudget = store!.bucket(`work-${job.workScope}`);
    const originalIntents = store!.db.prepare("SELECT count(*) n FROM intents").get()!.n, beforeRequests = requests, beforeReviews = reviewRequests;
    child.stdin.write(JSON.stringify({ id: "terminal-command", type: "prompt", message: `/orch resume ${job.id}` }) + "\n");
    let until = Date.now() + 10000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "terminal-command")) { if (Date.now() > until) throw new Error(output); await delay(20); }
    assert.ok(protocolEvents.some(event => event.type === "extension_ui_request" && event.method === "notify" && String(event.message).includes("TERMINAL_JOB")));
    assert.equal(requests, beforeRequests); statusJobId = job.id;
    child.stdin.write(JSON.stringify({ id: "terminal-tool", type: "prompt", message: "Attempt kernel_task resume for this existing completed job" }) + "\n");
    until = Date.now() + 15000;
    while (!parentToolResults.some(result => result.includes("TERMINAL_JOB"))) { if (Date.now() > until) throw new Error(JSON.stringify({output, errors, parentInputs})); await delay(20); }
    assert.ok(protocolEvents.some(event => event.type === "tool_execution_end" && event.toolName === "kernel_task" && event.isError === true && JSON.stringify(event.result).includes("TERMINAL_JOB")));
    assert.equal(requests, beforeRequests + 2); assert.equal(reviewRequests, beforeReviews); assert.equal(writes, 1);
    assert.deepEqual(store!.get("managed-jobs", job.id), originalJob); assert.deepEqual(store!.get("jobs", job.id), originalPlan);
    assert.deepEqual(store!.bucket(`work-${job.workScope}`), originalBudget); assert.equal(store!.db.prepare("SELECT count(*) n FROM intents").get()!.n, originalIntents);
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("TERMINAL_JOB"));
    retained("AC24","terminal-resume",()=>{assert.deepEqual(store!.get("managed-jobs",job!.id),originalJob);assert.deepEqual(store!.get("jobs",job!.id),originalPlan);assert.equal(writes,1);assert.equal(reviewRequests,beforeReviews);});
  }

  if (variant.startsWith("worker-compaction-")) {
    const runtime = JSON.parse(readFileSync(join(state, "artifacts", job.outputs.implement), "utf8"));
    assert.ok(summaryRequests > 0); assert.equal(runtime.status, "ended");
    assert.ok(runtime.observations.some((item: {contextOperations?: Array<{status: string; error?: string}>}) => item.contextOperations?.some(operation => operation.status === "failed" && operation.error?.includes("fixture_compaction_failure"))));
    assert.ok(job.failures.some(failure => failure.message.includes("fixture_compaction_failure")));
    assert.ok(job.receipt!.failureHistory.some(failure => failure.message.includes("fixture_compaction_failure")));
    assert.equal(job.semanticAttempts, 1); assert.equal(writes, 1); assert.equal(job.verification["focused-tests"].status, "passed");
    if (variant === "worker-compaction-quota") {
      assert.ok(compactionNotBefore); assert.ok(reviewCooldowns.length >= 2);
      assert.ok(reviewCooldowns.every(item => item.at >= compactionNotBefore), "review bypassed the observed helper Retry-After");
      assert.ok(reviewCooldowns[0].incident); assert.equal(reviewCooldowns[0].incident!.status, "OPEN");
      assert.ok(reviewCooldowns[0].incident!.notBefore >= compactionNotBefore);
    }
    statusJobId = job.id;
    child.stdin.write(JSON.stringify({ id: "worker-context-ui", type: "prompt", message: `/orch status ${job.id}` }) + "\n");
    let until = Date.now() + 10000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "worker-context-ui")) { if (Date.now() > until) throw new Error(output); await delay(20); }
    child.stdin.write(JSON.stringify({ id: "worker-context-parent", type: "prompt", message: "Use kernel_task status to report the task and its retained errors" }) + "\n");
    until = Date.now() + 15000;
    while (!parentToolResults.some(result => result.includes("CONTEXT_COMPACTION_FAILED"))) { if (Date.now() > until) throw new Error(JSON.stringify({output, errors, parentInputs})); await delay(20); }
    const ui = protocolEvents.filter(event => event.type === "extension_ui_request" && event.method === "notify")
      .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).filter(value => value.id === job!.id && value.failureGroups).at(-1);
    const tool = protocolEvents.find(event => event.type === "tool_execution_end" && event.toolName === "kernel_task" && event.result?.details?.id === job!.id);
    const records = process.env.TASK_KEEPER_TEST_RECORD_DIR;
    if (records) {
      const path = join(dirname(records), "workflow-context-observers"); mkdirSync(path, { recursive: true });
      writeFileSync(join(path, `${variant}.json`), JSON.stringify({ summaryRequests, compactionNotBefore, reviewCooldowns,
        runtime, job, ui, tool, parentInput: parentInputs.at(-1) }, null, 2));
    }
    assert.ok(ui.failureGroups.some((group: {sample: string}) => group.sample.includes("fixture_compaction_failure")));
    assert.ok(tool); assert.deepEqual(JSON.parse(tool.result.content[0].text), tool.result.details);
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("fixture_compaction_failure"));
  }

  if (variant === "network-recovery") {
    assert.equal(job.recovery?.incidentDomain?.kind, "transport"); assert.equal(job.recovery?.networkAttempts, 1);
    assert.equal(store!.list("incidents").length, 0);
    assert.equal(store!.get<{ status: string }>("transport-incidents", config.routes.primary.transportDomain)?.status, "CLOSED");
    assert.equal(job.semanticAttempts, 1);
  }
  if (variant === "quota-recovery" || variant.startsWith("fallback")) {
    assert.equal(job.semanticAttempts, 1); assert.ok(job.failures.some((failure) => failure.layer === "provider"));
    assert.ok(job.recovery?.incidentId);
    if (variant.startsWith("fallback")) { assert.equal(job.routes?.implement, "backup"); assert.ok(Number(store!.bucket(`incident-${job.recovery!.incidentId}`)?.used) > 0); }
    if (variant === "fallback") {
      const backupHandoff = backupHandoffs[0];
      assert.ok(backupHandoff); assert.equal(backupHandoff!.implementationStatus, "passed"); assert.equal(backupHandoff!.job.routes!.implement, "backup");
      assert.equal(backupHandoff!.incident.status, "OPEN"); assert.equal(backupHandoff!.incident.id, job.recovery!.incidentId);
      assert.equal(backupHandoff!.job.semanticAttempts, 1); assert.equal(backupHandoff!.used, 2); assert.equal(backupHandoff!.reserved, 0);
      assert.equal(Number(store!.bucket(`incident-${job.recovery!.incidentId}`)!.used), backupHandoff!.used);
      if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
        const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-observers"); mkdirSync(path, { recursive: true });
        writeFileSync(join(path, "backup-handoff.json"), JSON.stringify({ beforePrimaryReply: backupHandoff, finalJob: job, requestedModels }, null, 2));
      }
      const route = job.receipt!.routes!.find(row => row.stepId === "implement")!;
      assert.equal(route.configuredRoute, "primary"); assert.equal(route.selectedRoute, "backup"); assert.equal(route.recovery!.incidentId, job.recovery!.incidentId);
      assert.ok(route.attempts.some(attempt => attempt.observed?.some(observation => observation.model === "fixture-model" && observation.stopReason === "error")));
      assert.ok(route.attempts.some(attempt => attempt.observed?.some(observation => observation.model === "fixture-backup" && observation.stopReason === "stop")));
    }
  }
  if (variant.startsWith("fallback-skip")) {
    assert.equal(requestedModels.includes("fixture-rejected"), false); assert.equal(requestedModels.includes("fixture-backup"), true);
    const assessment = store!.get<{ rejected: Array<{ id: string; reasons: string[] }> }>("route-assessments", job.id)!;
    const expected = variant === "fallback-skip-network" ? "network_not_certified" : variant === "fallback-skip-telemetry" ? "quota_telemetry_not_eligible"
      : variant === "fallback-skip-context" ? "required_context_not_available" : "thinking_level_not_supported";
    assert.ok(assessment.rejected.some(route => route.id === "rejected" && route.reasons.includes(expected)));
    if (variant === "fallback-skip-context") for (const id of ["RTB-001", "T27", "T78"]) evidence(id, () => {
      assert.equal(requestedModels.includes("fixture-rejected"), false); assert.equal(job.routes?.implement, "backup");
      assert.ok(assessment.rejected.some(route => route.id === "rejected" && route.reasons.includes("required_context_not_available")));
      const observations = store!.list<{ model: string }>("child-observations").map(row => row.value);
      assert.equal(observations.some(o => o.model === "fixture-rejected"), false); assert.ok(observations.some(o => o.model === "fixture-backup"));
      const catalog = JSON.parse(readFileSync(join(agentDir, "models.json"), "utf8")).providers["fixture-provider"].models;
      const rejected = catalog.find((m: {id: string}) => m.id === "fixture-rejected"), backup = catalog.find((m: {id: string}) => m.id === "fixture-backup");
      assert.ok(rejected.cost.input < backup.cost.input); assert.ok(rejected.maxTokens > backup.maxTokens); assert.ok(rejected.contextWindow < 16000);
    });
  }
  if (variant.startsWith("replan-")) {
    const plan = store!.get<{semanticReplans?:number;dispatched:number;spec:{required:string[];maxSemanticReplans:number};steps:Array<{id:string;dependencies:string[];status:string}>}>("jobs", job.id)!;
    const expected = variant === "replan-repair" ? 1 : 0;
    assert.equal(job.status, "COMPLETED"); assert.equal(plan.semanticReplans ?? 0, expected); assert.equal(plan.spec.maxSemanticReplans, expected);
    assert.equal(plan.steps.filter(step => step.id.startsWith("replan:diagnose:")).length, expected);
    assert.equal(diagnosisRequests, expected * 2); assert.equal(writes, variant === "replan-repair" ? 3 : 2); assert.equal(job.semanticAttempts, writes);
    assert.deepEqual(plan.spec.required, ["build", "focused-tests", "independent-review"]);
    assert.equal(plan.dispatched, variant === "replan-repair" ? 12 : 8);
    if (expected) {
      assert.deepEqual(plan.steps.find(step => step.id === "implement")!.dependencies, ["replan:diagnose:1"]);
      assert.equal(plan.steps.find(step => step.id === "replan:diagnose:1")!.status, "passed");
      assert.equal(store!.list("plan-revisions").length, 1); assert.equal(diagnosisWriterInputs.length, 2);
      assert.ok(diagnosisWriterInputs.every(input => JSON.stringify(input).includes("DIAGNOSIS_FIXTURE_MARKER")));
      assert.ok(JSON.stringify(diagnosisInputs[0]).includes("CHECK:focused-tests"));
    }
    assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n'); assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs);
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"replan-observers");mkdirSync(path,{recursive:true});
      writeFileSync(join(path,`${variant}.json`),JSON.stringify({job,plan,diagnosisInputs,diagnosisWriterInputs,diagnosisRequests,requests,writes,revisions:store!.list("plan-revisions")},null,2)); }
  }
  if (variant === "quota-recovery") {
    assert.equal(store!.get<{semanticReplans?:number}>("jobs", job.id)?.semanticReplans ?? 0, 0); assert.equal(diagnosisRequests, 0);
  }
  if (variant === "proposal-valid" || variant === "proposal-tool") {
    for (const id of coverageIds[variant].split(" ")) evidence(id, () => {
      const associated = store!.list<{contract: {jobId: string; proposal: {target: string}}}>("proposal-executions"); assert.equal(associated.length, 1);
      assert.equal(associated[0].value.contract.jobId, job.id); assert.equal(associated[0].value.contract.proposal.target, "baseline:build");
      assert.equal(store!.intent(associated[0].id)!.status, "settled"); assert.equal(store!.get("pending-proposals", job.id), null);
      assert.equal(store!.get<{dispatched: number}>("jobs", job.id)!.dispatched, 5); assert.equal(job.status, "COMPLETED"); assert.equal(store!.list("proposals").length, variant === "proposal-valid" ? 2 : 1);
      if (variant === "proposal-tool") { assert.equal(parentRequests, 3); assert.ok(parentToolResults.some(value => value.includes("accepted"))); }
    });
    if (variant === "proposal-valid") {
      statusJobId = job.id; child.stdin.write(JSON.stringify({ type: "prompt", id: "proposal-summary", message: "Report the verified receipt and rejected proposal history." }) + "\n");
      const until = Date.now() + 15000;
      while (!parentToolResults.some(value => value.includes("COMPLETED")) || !protocolEvents.some(event => event.type === "agent_end")) { if (Date.now() > until) throw new Error(output); await delay(20); }
      for (const id of coverageIds[variant].split(" ")) evidence(id, () => {
        assert.ok(JSON.stringify(parentInputs.at(-1)).includes("proposalRejections")); assert.ok(JSON.stringify(parentInputs.at(-1)).includes("INVALID_PROPOSAL_JSON"));
        assert.ok(JSON.stringify(parentInputs.at(-1)).includes("COMPLETED")); assert.equal(parentRequests, 2);
      });
    }
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "proposal-observers"); mkdirSync(path, {recursive:true});
      writeFileSync(join(path, `${variant}.json`), JSON.stringify({ job, proposalWitness, parentInputs, parentToolResults, executions: store!.list("proposal-executions"), requests, writes }, null, 2)); }
  }
  if (usesShared) {
    const releaseDeadline = Date.now() + 10000;
    while (store!.claims().some(claim => String(claim.resource_id).startsWith("shared-directory-"))) {
      if (Date.now() > releaseDeadline) throw new Error("shared directory claims did not settle"); await delay(20);
    }
    for (const id of (variant.startsWith("proposal-") ? coverageIds[variant].split(" ") : ["SCH-009", "TK05"])) evidence(id, () => {
      assert.equal(sharedReleased, true); assert.equal(job.status, "COMPLETED"); assert.equal(writes, 1);
      assert.equal(readFileSync(join(sharedRoot, "checks.txt"), "utf8"), "check\ncheck\n");
      assert.equal(store!.intent(sharedIntent!)!.status, "settled"); assert.ok(sharedObservations.length >= 2);
      const writerRequests = sharedObservations.filter((value: any) => value.kind === "writer-request") as Array<{claims: Array<{intent: {kind: string; payload: {jobId: string}}}>}>;
      assert.ok(writerRequests.length > 0);
      for (const observation of writerRequests) { assert.equal(observation.claims.length, 1); assert.equal(observation.claims[0].intent.kind, "write"); assert.equal(observation.claims[0].intent.payload.jobId, job.id); }
      assert.deepEqual(job.sharedWriteResources, sharedWriteResources({ build: config.verificationBindings.build }));
      assert.equal(job.verification.build.status, "passed"); assert.equal(job.verification["focused-tests"].status, "passed");
    });
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "shared-resource-observers"); mkdirSync(path, {recursive:true});
      writeFileSync(join(path, "workflow.json"), JSON.stringify({ job, sharedObservations, requests, writes, claims: store!.claims() }, null, 2)); }
  }
  if (variant === "build-repair") { assert.equal(job.semanticAttempts, 2); assert.ok(job.failures.some((failure) => failure.code === "CHECK:build" && failure.resolvedBy)); }
  if (variant === "check-approval") { assert.equal(job.receipt?.specVersion, 2); assert.equal(job.semanticAttempts, 1); assert.ok(job.outputs.checkApproval); }
  if (variant === "combined-recipes") { assert.equal(job.upgradesUsed ?? 0, 0); assert.equal(job.critiquesUsed, 2); assert.equal(job.semanticAttempts, 3); assert.ok(job.failures.some((failure) => failure.code === "CHECK:focused-tests" && failure.resolvedBy)); }
  if (variant.startsWith("scope-") && variant !== "scope-fork-cap") {
    const expected = variant === "scope-job-cap" ? "WORK_SCOPE_JOB_LIMIT" : "WORK_SCOPE_SEMANTIC_LIMIT";
    assert.ok(parentToolResults.some(result => result.includes(expected)), JSON.stringify(parentToolResults));
    assert.equal(store!.list("managed-jobs").length, 1); assert.equal(writes, 1); assert.equal(job.semanticAttempts, 1);
    assert.equal(store!.list("jobs").length, 1); assert.ok(reviewRequests >= 2);
    if (variant === "scope-semantic-cap") for (const id of ["SCH-001", "T30"]) evidence(id, () => {
      assert.ok(parentToolResults.some(result => result.includes("WORK_SCOPE_SEMANTIC_LIMIT")));
      assert.equal(store!.list<ManagedJob>("managed-jobs").filter(row => row.value.workScope === job.workScope).length, 1);
      assert.equal(job.semanticAttempts, 1); assert.equal(writes, 1); assert.equal(job.receipt?.status, "COMPLETED");
    });
  }
  if (variant === "model-control-race") for (const id of ["CFG-001", "REC-019"]) evidence(id, () => {
    assert.equal(staleReplyDenied, true); assert.equal(resumedViaCommand, true); assert.equal(job!.status, "COMPLETED");
    assert.equal(store!.list("managed-jobs").length, 1); assert.equal(job!.semanticAttempts, 1);
  });
  if(variant === "tool-entry"){
    const ledger=new UsageLedger(store!),task=ledger.task(job.analyticsTaskId!),facts=ledger.facts(task.id);
    acceptance("AC11","child-job",{level:"E",observer:"actual-parent-tool-and-child-descriptor-usage-links",predicate:"derived jobs share the parent logical statistics task",artifact:observerArtifact("child-job-usage",{job,task,facts})},()=>{
      assert.notEqual(task.id,job.id);assert.equal(task.status,"open");assert.ok(facts.some(f=>f.role==="parent"));assert.ok(facts.some(f=>f.role==="implement"));assert.equal(ledger.hasTask(job.id),false);
      assert.equal(job.status,"COMPLETED");assert.equal(job.workScope,store!.get<ManagedJob>("managed-jobs",job.id)!.workScope);
    });
  }
  if(variant === "tool-entry")retained("AC24","tool-command-shared",()=>{assert.equal(pausedViaCommand,true);assert.equal(resumedViaCommand,true);assert.equal(job!.status,"COMPLETED");assert.equal(store!.list("managed-jobs").length,1);});
  if (variant === "tool-entry") evidence("CFG-001", () => {
    assert.equal(pausedViaCommand, true); assert.equal(resumedViaCommand, true);
    assert.equal(store!.list("managed-jobs").length, 1); assert.ok(parentToolResults.some(result => result.includes(job!.id)));
    assert.ok(job!.controlEpoch >= 3); assert.equal(job!.status, "COMPLETED");
  });
  if (variant === "recovered-tool-error") { assert.ok(job.failures.some((failure) => failure.layer === "tool" && failure.resolvedBy)); assert.equal(job.receipt?.failureHistory.length, job.failures.length); }
  if (variant === "multi-job") {assert.equal(independentCompleted,true);retained("AC09","independent-pools",()=>{assert.equal(independentCompleted,true);assert.equal(job!.status,"COMPLETED");assert.ok(requestedModels.includes("fixture-independent"));});}
  if(variant === "opinion-revise")acceptance("AC16","evidence-rebuttal",{level:"E",observer:"actual-A-rebuttal-and-B-withdrawal-on-unchanged-source",predicate:"no-code rebuttal consumes an exchange and requires B confirmation",artifact:observerArtifact("opinion-rebuttal",{job,reviewInputs,writes})},()=>{
    assert.equal(writes,1);assert.equal(job!.opinion!.exchanges,1);assert.equal(job!.opinion!.reviews[0].snapshot,job!.opinion!.reviews[1].snapshot);assert.ok(job!.opinion!.summary!.includes("Withdraw second-view"));assert.ok(reviewInputs.some(input=>JSON.stringify(input).includes("EVIDENCE_REBUTTAL")));assert.ok(job!.opinion!.findingStates!.some(finding=>finding.id==="second-view"&&finding.state==="resolved"));
  });
  if(variant === "opinion-revise"){
    assert.equal(job.opinion?.exchanges,1);assert.equal(job.opinion?.reviews.length,2);assert.deepEqual(job.opinion?.reviews.map(review=>review.passed),[false,true]);
    assert.equal(job.semanticAttempts,2);assert.equal(job.upgradesUsed??0,0);
  }
  if(variant === "second-opinion")acceptance("AC16","first-pass",{level:"E",observer:"actual-first-B-approval-and-required-checks",predicate:"agreement does not force unnecessary edits",artifact:observerArtifact("opinion-first-pass",{job,writes})},()=>{assert.equal(writes,1);assert.equal(job!.opinion!.exchanges,0);assert.equal(job!.opinion!.reviews.length,1);assert.equal(job!.opinion!.reviews[0].passed,true);assert.equal(job!.receipt!.status,"COMPLETED");});
  if(variant === "critique-revise"){
    const row=new UsageLedger(store!).query({taskId:job!.id})[0];
    acceptance("AC38","opinion-revision-reuse",{level:"E",observer:"actual-A-edit-B-recheck-reused-required-review-and-task-ledger",predicate:"second view revision reaches real acceptance with no duplicate review fee",artifact:observerArtifact("combined-opinion",{job,row,requests,reviewRequests,criticRequests})},()=>{assert.equal(job!.status,"COMPLETED");assert.equal(job!.opinion!.exchanges,1);assert.ok(job!.outputs.reviewReuse);assert.equal(reviewRequests,criticRequests);assert.ok(row.roles.includes("implement"));assert.ok(row.roles.includes("second-opinion"));assert.equal(row.rounds.requiredReview,0);assert.equal(row.task.resultSource,"verifier");});
  }
  if(variant === "critique-revise")acceptance("AC16","revise-and-recheck",{level:"E",observer:"actual-changed-candidate-and-B-recheck",predicate:"A changes source, checks rerun, then B approves current snapshot",artifact:observerArtifact("opinion-revise-recheck",{job,reviewInputs,writes})},()=>{assert.equal(job!.opinion!.exchanges,1);assert.notEqual(job!.opinion!.reviews[0].snapshot,job!.opinion!.reviews[1].snapshot);assert.equal(job!.opinion!.reviews[1].snapshot,job!.snapshot);assert.equal(job!.opinion!.reviews[1].passed,true);assert.ok(job!.checks.some(check=>check.checkId==="focused-tests"&&check.status==="passed"&&check.snapshot===job!.snapshot));});
  if(variant === "second-opinion"){
    assert.equal(job.opinion?.reviews.length,1);assert.equal(job.opinion?.reviews[0].passed,true);assert.equal(job.opinion?.exchanges,0);
    assert.ok(job.checks.some(check=>check.checkId==="second-opinion"&&check.status==="passed"));
    assert.ok(job.checks.some(check=>check.checkId==="independent-review"&&check.status==="passed"));
  }
  if(variant === "same-model-repair")acceptance("AC30","implementation-fail",{level:"E",observer:"native-workflow-and-receiver",predicate:"same-model repair with real rechecks",artifact:observerArtifact("same-model-repair",{job,requestedModels,requests})},()=>{
    assert.equal(job.upgradesUsed??0,0);assert.equal(job.semanticAttempts,2);assert.equal(job.routes?.implement??"primary","primary");assert.equal(requestedModels.includes("fixture-backup"),false);assert.equal(job.receipt?.status,"COMPLETED");
  });
  if (variant === "same-model-repair") { assert.equal(job.upgradesUsed ?? 0, 0); assert.equal(job.routes?.implement ?? "primary", "primary"); assert.equal(job.semanticAttempts, 2); }
  if (variant === "critique" || variant === "critique-revise") {
    assert.ok(criticRequests > 0); assert.equal(job.critiquesUsed, variant === "critique"?1:2); assert.equal(job.semanticAttempts, variant === "critique" ? 1 : 2);
    assert.ok(job.checks.some((check) => check.checkId === "independent-review" && check.status === "passed"));
  }
  assert.equal(job.receipt?.status, "COMPLETED"); assert.ok(reviewRequests >= 2); assert.ok(job.cwd);
  assert.equal(JSON.parse(readFileSync(join(job.cwd!, "answer.json"), "utf8")).answer, workflow === "fix" ? 2 : 1);
  assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n'); assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs);
  assert.equal(readFileSync(join(job.cwd!, "user-edit.txt"), "utf8"), "preserved\n");
  if (workflow === "fix") assert.equal(job.verification["focused-tests"].counts?.passed, 1);
  if (["fix", "repair"].includes(variant)) {
    const originalBudget = store!.bucket(`work-${job.workScope}`), originalWrites = writes; statusJobId = job.id;
    child.stdin.write(JSON.stringify({ id: "receipt-ui", type: "prompt", message: `/orch status ${job.id}` }) + "\n");
    let until = Date.now() + 10000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "receipt-ui")) { if (Date.now() > until) throw new Error(output); await delay(20); }
    child.stdin.write(JSON.stringify({ id: "receipt-model", type: "prompt", message: "Use kernel_task status to report this completed task and its evidence" }) + "\n");
    until = Date.now() + 15000;
    while (!parentToolResults.some(result => result.includes(job!.id)) || !protocolEvents.some(event => event.type === "tool_execution_end" && event.toolName === "kernel_task")) { if (Date.now() > until) throw new Error(JSON.stringify({output, errors, parentInputs})); await delay(20); }
    const ui = protocolEvents.filter(event => event.type === "extension_ui_request" && event.method === "notify")
      .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).filter(value => value.id === job!.id && value.receipt).at(-1);
    const tool = protocolEvents.filter(event => event.type === "tool_execution_end" && event.toolName === "kernel_task").at(-1)!.result;
    const content = JSON.parse(tool.content.find((item: {type: string}) => item.type === "text").text);
    const plan = store!.get<{spec:{id:string;version:number;snapshot:string;required:string[]}}>("jobs", job.id)!;
    const runtime = JSON.parse(readFileSync(join(state, "artifacts", job.outputs.implement), "utf8"));
    for (const id of ["WFL-012", "EVD-012", ...(variant === "fix" ? ["EXE-007"] : [])]) evidence(id, () => {
      assert.equal(runtime.status, "ended"); assert.equal(job!.receipt!.jobId, plan.spec.id);
      if(id === "EXE-007") {
        const descriptor=JSON.parse(readFileSync(join(state,"child-contexts",`${runtime.descriptorId}.json`),"utf8")), observed=runtime.observations[0];
        assert.ok(runtime.nativeRunId);assert.equal(runtime.nativeStatus,"completed");assert.equal(runtime.nativeExitCode,0);assert.equal(runtime.terminationConfirmed,true);
        assert.equal(descriptor.jobId,job!.id);assert.equal(descriptor.stepId,"implement");assert.equal(runtime.observations.length,1);
        assert.equal(observed.descriptorId,runtime.descriptorId);assert.equal(observed.ready,true);assert.equal(observed.settled,true);assert.equal(observed.cwd,job!.cwd);
        assert.equal(observed.provider,config.routes.primary.provider);assert.equal(observed.model,config.routes.primary.model);assert.equal(observed.thinking,config.executionProfiles.worker.thinking);
        assert.equal(observed.modelDigest,descriptor.modelDigest);assert.equal(observed.runtimeDigest,descriptor.runtimeDigest);
        assert.ok(store!.events(job!.workScope).some(event=>event.producer===observed.producerId));assert.equal(store!.sequenceGaps(job!.workScope).length,0);
        assert.equal(store!.get<{jobId:string}>("artifacts",job!.outputs.implement)!.jobId,job!.id);
      }
      assert.equal(job!.receipt!.specVersion, plan.spec.version); assert.equal(job!.receipt!.snapshot, plan.spec.snapshot);
      assert.deepEqual(plan.spec.required, ["build", "focused-tests", "independent-review"]);
      for (const view of [job!, ui, tool.details, content]) {
        assert.equal(view.status, "COMPLETED"); assert.equal(view.receipt.status, "COMPLETED");
        assert.equal(view.id, job!.id); assert.equal(view.receipt.specVersion, plan.spec.version); assert.equal(view.receipt.snapshot, plan.spec.snapshot);
        for (const attempt of view.receipt.routes.find((route: {stepId:string}) => route.stepId === "implement").attempts) {
          for (const observed of attempt.observed ?? []) {
            assert.equal(observed.identitySource, "client_configuration"); assert.equal(observed.responseModel, null); assert.equal(observed.serverWeights, "unverified");
          }
        }
      }
      for (const checkId of ["build", "focused-tests"]) {
        const result: VerificationResult = job!.verification[checkId]; assert.equal(result.terminationConfirmed, true); assert.equal(result.terminationCoverage, "pid-namespace");
        assert.equal(result.notSent, false); assert.equal(result.jobId, job!.id); assert.equal(result.snapshot, plan.spec.snapshot);
        assert.equal(result.exitCode, 0); assert.equal(result.status, "passed");
      }
      assert.equal(job!.verification["focused-tests"].counts!.tests, 1); assert.equal(job!.verification["focused-tests"].counts!.passed, 1);
      assert.ok(job!.checks.some(check => check.checkId === "independent-review" && check.status === "passed" && check.snapshot === plan.spec.snapshot));
      assert.ok(JSON.stringify(parentInputs.at(-1)).includes(plan.spec.snapshot)); assert.ok(parentToolResults.some(result => result.includes(job!.id)));
      assert.equal(git("status", "--porcelain=v1"), before); assert.equal(git("show-ref"), refs); assert.equal(writes, originalWrites);
      assert.deepEqual(store!.bucket(`work-${job!.workScope}`), originalBudget); assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
    });
    if (variant === "repair") evidence("EVD-003", () => {
      assert.equal(job!.semanticAttempts, 2); assert.equal(writes, 2);
      assert.ok(job!.receipt!.failureHistory.some(failure => failure.code === "CHECK:focused-tests" && failure.resolvedBy));
      for (const view of [ui, tool.details, content]) assert.ok(view.failureGroups.some((failure: {code:string;unresolved:number;count:number}) => failure.code === "CHECK:focused-tests" && failure.unresolved === 0 && failure.count >= 1));
      assert.ok(JSON.stringify(parentInputs.at(-1)).includes("CHECK:focused-tests"));
      assert.equal(job!.verification["focused-tests"].counts!.passed, 1);
    });
    if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "receipt-observers"); mkdirSync(path, { recursive: true });
      writeFileSync(join(path, `${variant}.json`), JSON.stringify({ job, runtime, plan, ui, tool, parentInput: parentInputs.at(-1), writes, reviewRequests, mainStatus: git("status", "--porcelain=v1"), refs: git("show-ref") }, null, 2)); }
  }
  if (variant === "critic-reserve") {
    const plan=store!.get<{spec:{required:string[]};steps:Array<{id:string;status:string}>}>("jobs",job.id)!;
    assert.ok(job.outputs.reviewReuse);assert.equal(job.critiquesUsed,1);assert.equal(job.semanticAttempts,1);
    assert.equal(plan.steps.find(step=>step.id==="second-opinion")!.status,"passed");assert.equal(plan.steps.find(step=>step.id==="independent-review")!.status,"passed");
    assert.ok(plan.spec.required.includes("independent-review"));assert.equal(job.receipt!.status,"COMPLETED");
    assert.ok(Number(store!.bucket(`work-${job.workScope}`)!.used)<=6);assert.equal(store!.bucket(`work-${job.workScope}`)!.reserved,0);
    assert.equal(reviewRequests,criticRequests);assert.ok(criticRequests>0);
  }
  if (variant === "scope-fork-cap") {
    const originalScope = job.workScope, originalBudget = store!.bucket(`work-${originalScope}`), originalRequests = requests;
    child.stdin.write(JSON.stringify({ id: "fork-before-marker", type: "fork", entryId: "seed-user" }) + "\n");
    let until = Date.now() + 15000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "fork-before-marker")) {
      if (Date.now() > until) throw new Error(JSON.stringify({ output, errors })); await delay(20);
    }
    const forked = protocolEvents.find(event => event.type === "response" && event.id === "fork-before-marker")!;
    assert.equal(forked.success, true, JSON.stringify(forked)); assert.equal(forked.data.cancelled, false);
    child.stdin.write(JSON.stringify({ id: "fork-state", type: "get_state" }) + "\n"); until = Date.now() + 10000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "fork-state")) { if (Date.now() > until) throw new Error(output); await delay(20); }
    const session = protocolEvents.find(event => event.type === "response" && event.id === "fork-state")!.data;
    child.stdin.write(JSON.stringify({ id: "fork-replacement", type: "prompt", message: "Use kernel_task fix to start a replacement task" }) + "\n"); until = Date.now() + 15000;
    while (!parentToolResults.some(result => result.includes("WORK_SCOPE_SEMANTIC_LIMIT"))) {
      if (Date.now() > until) throw new Error(JSON.stringify({ output, errors, session, scopes: store!.list("session-scopes") })); await delay(20);
    }
    for (const id of ["SCH-001", "T30"]) evidence(id, () => {
      assert.notEqual(session.sessionId, job!.parentSessionId); assert.equal(store!.get<{scopeId:string}>("session-scopes", session.sessionId)!.scopeId, originalScope);
      assert.equal(store!.list<ManagedJob>("managed-jobs").filter(row => row.value.workScope === originalScope).length, 1);
      assert.equal(store!.get<ManagedJob>("managed-jobs", job!.id)!.semanticAttempts, 1); assert.equal(writes, 1);
      assert.deepEqual(store!.bucket(`work-${originalScope}`), originalBudget); assert.equal(requests - originalRequests, 2);
      assert.ok(parentToolResults.some(result => result.includes("WORK_SCOPE_SEMANTIC_LIMIT"))); assert.equal(job!.receipt!.status, "COMPLETED");
    }); return;
  }
  if (variant.startsWith("packet-overflow")) {
    const beforeRequests = requests, eventOffset = protocolEvents.length; statusJobId = job.id;
    child.stdin.write(JSON.stringify({ id: "overflow-prompt", type: "prompt", message: "Report this existing job's receipt using kernel_task status" }) + "\n");
    let until = Date.now() + 15000;
    while (!protocolEvents.slice(eventOffset).some(event => event.type === "agent_settled")) {
      if (Date.now() > until) throw new Error(JSON.stringify({ output, errors, requests })); await delay(20);
    }
    child.stdin.write(JSON.stringify({ id: "overflow-doctor", type: "prompt", message: "/orch doctor" }) + "\n"); until = Date.now() + 10000;
    while (!protocolEvents.some(event => event.type === "response" && event.id === "overflow-doctor")) {
      if (Date.now() > until) throw new Error(output); await delay(20);
    }
    const doctor = protocolEvents.filter(event => event.type === "extension_ui_request" && event.method === "notify")
      .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).filter(value => value.contextEvidence).at(-1);
    for (const id of ["EVD-005", "T56"]) evidence(id, () => {
      assert.equal(parentRequests, 0); assert.equal(requests, beforeRequests);
      if(id === "EVD-005" && variant === "packet-overflow")acceptance("AC26","packet-overflow",{level:"E",observer:"actual-parent-request-denial-and-doctor-context-projection",predicate:"oversized required facts block the outgoing request without losing the prior receipt",artifact:observerArtifact("packet-overflow",{doctor,beforeRequests,requests,job,parentRequests})},()=>{assert.equal(requests,beforeRequests);assert.equal(parentRequests,0);assert.equal(doctor.contextEvidence.blocked.code,"PACKET_TOO_LARGE");assert.equal(doctor.contextEvidence.packet,null);assert.equal(store!.get<ManagedJob>("managed-jobs",job!.id)!.receipt!.status,"COMPLETED");});
      assert.equal(doctor.contextEvidence.blocked.code, "PACKET_TOO_LARGE"); assert.equal(doctor.contextEvidence.byteBudget, 128);
      assert.equal(doctor.contextEvidence.packet, null); assert.ok(doctor.contextEvidence.blocked.message.includes("UTF-8 bytes"));
      assert.equal(store!.get<ManagedJob>("managed-jobs", job!.id)!.receipt!.status, "COMPLETED"); assert.equal(writes, 1);
      assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      if (variant === "packet-overflow-no-abort") {
        assert.ok(store!.list<{reason:string}>("request-denials").some(row => row.value.reason === "PACKET_TOO_LARGE"));
        assert.ok(store!.list<{category:string}>("native-errors").some(row => row.value.category === "context_contract"));
        assert.ok(existsSync(join(root, "context-abort-control.json")));
      }
    }); return;
  }
  if (variant === "combined-tool-recovery") {
    const until = Date.now() + 15000;
    while (!store!.list<{status:string}>("recovery").some(row => row.value.status === "DONE")) {
      if (Date.now() > until) throw new Error(JSON.stringify({records: store!.list("recovery"), output, errors})); await delay(20);
    }
    {
      assert.equal(parentRequests, 3); assert.equal(store!.list("managed-jobs").length, 1);
      assert.equal(job!.receipt?.status, "COMPLETED"); assert.equal(job!.semanticAttempts, 1); assert.equal(writes, 1);
      assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
      const recovery = store!.list<{status:string;attempts:number}>("recovery")[0].value;
      assert.equal(recovery.status, "DONE"); assert.equal(recovery.attempts, 1);
    }
  }
  if (variant === "candidate-edit") {
    const originalReceipt=structuredClone(job.receipt), originalSteps=store!.get<{dispatched:number}>("jobs",job.id)!.dispatched;
    const originalBudget=store!.bucket(`work-${job.workScope}`), source=join(job.cwd!,"answer.json"), bytes=readFileSync(source);
    const query=async(id:string)=>{
      const offset=protocolEvents.length;child.stdin.write(JSON.stringify({id,type:"prompt",message:`/orch status ${job.id}`})+"\n");const until=Date.now()+10000;
      while(!protocolEvents.slice(offset).some(event=>event.type==="response"&&event.id===id)){if(Date.now()>until)throw new Error(output);await delay(20);}
      return protocolEvents.slice(offset).filter(event=>event.type==="extension_ui_request"&&event.method==="notify").flatMap(event=>{try{return[JSON.parse(event.message)];}catch{return[];}}).find(value=>value.id===job!.id&&typeof value.receiptCurrent==="boolean");
    };
    const initial=await query("candidate-before");assert.equal(initial.receiptCurrent,true);assert.equal(initial.status,"COMPLETED");
    writeFileSync(source,'{"answer":3}\n');const changed=await query("candidate-changed");
    assert.equal(changed.receiptCurrent,false);assert.equal(changed.status,"BLOCKED");assert.equal(changed.receipt.status,"BLOCKED");
    assert.equal(changed.receipt.previouslyAcceptedSnapshot,originalReceipt!.snapshot);assert.equal(changed.reason,"receipt_invalidated_by_candidate_or_policy_change");
    assert.deepEqual(store!.get<ManagedJob>("managed-jobs",job.id)!.receipt,originalReceipt);
    statusJobId=job.id;const beforeQuery=requests;child.stdin.write(JSON.stringify({id:"candidate-tool",type:"prompt",message:"Use kernel_task status to inspect whether this candidate receipt is still current"})+"\n");
    let until=Date.now()+15000;
    while(!parentToolResults.some(result=>result.includes("receipt_invalidated"))||!protocolEvents.some(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task")){if(Date.now()>until)throw new Error(output);await delay(20);}
    const tool=protocolEvents.filter(event=>event.type==="tool_execution_end"&&event.toolName==="kernel_task").at(-1)!.result;
    assert.equal(tool.details.receiptCurrent,false);assert.equal(tool.details.status,"BLOCKED");assert.deepEqual(JSON.parse(tool.content[0].text),tool.details);
    assert.ok(JSON.stringify(parentInputs.at(-1)).includes("receipt_invalidated"));assert.equal(requests-beforeQuery,2);
    writeFileSync(source,bytes);const restored=await query("candidate-restored");assert.equal(restored.receiptCurrent,true);assert.equal(restored.status,"COMPLETED");
    assert.equal(writes,1);assert.equal(store!.get<{dispatched:number}>("jobs",job.id)!.dispatched,originalSteps);assert.deepEqual(store!.bucket(`work-${job.workScope}`),originalBudget);
    assert.equal(readFileSync(join(cwd,"answer.json"),"utf8"),'{"answer":1}\n');assert.equal(git("status","--porcelain=v1"),before);assert.equal(git("show-ref"),refs);
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"receipt-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,"candidate-edit.json"),JSON.stringify({originalReceipt,initial,changed,tool,restored,originalSteps,writes,parentInput:parentInputs.at(-1)},null,2));}
  }
  if (variant === "runtime-upgrade") {
    const beforeRequests = requests, previousReceipt = structuredClone(job.receipt);
    const exited = once(child, "exit"); child.kill("SIGTERM"); await exited;
    const reviewFile = join(pkg, "src/verification/review.ts"); writeFileSync(reviewFile, readFileSync(reviewFile, "utf8") + "\n// New acceptance implementation identity\n");
    output = ""; errors = ""; child = launch(job.parentSessionId); watchChild();
    child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch status ${job.id}`, id: "upgraded-runtime-status" }) + "\n");
    let presented: {status:string;receiptCurrent:boolean;reason:string;receipt:{status:string}} | undefined;
    const until = Date.now() + 10000;
    while (!presented) {
      for (const line of output.split("\n")) try {
        const event = JSON.parse(line); if (event.type !== "extension_ui_request" || event.method !== "notify") continue;
        const value = JSON.parse(event.message); if (value.id === job.id && typeof value.receiptCurrent === "boolean") presented = value;
      } catch {}
      if (Date.now() > until) throw new Error(JSON.stringify({output, errors})); if (!presented) await delay(20);
    }
    for (const id of ["EXE-002", "WFL-005"]) evidence(id, () => {
      assert.equal(presented!.receiptCurrent, false); assert.equal(presented!.status, "BLOCKED");
      assert.equal(presented!.receipt.status, "BLOCKED"); assert.equal(presented!.reason, "acceptance_inputs_changed_or_unavailable");
      assert.equal(requests, beforeRequests); assert.deepEqual(store!.get<ManagedJob>("managed-jobs", job.id)!.receipt, previousReceipt);
      assert.equal(JSON.parse(readFileSync(join(job.cwd!, "answer.json"), "utf8")).answer, 2);
    });
  }
  if (variant === "artifact-loss") {
    const beforeRequests = requests, artifact = job.outputs["focused-tests"];
    assert.ok(artifact); const artifactPath = join(state, "artifacts", artifact), saved = readFileSync(artifactPath);
    const query = async () => {
      output = "";
      child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch status ${job.id}`, id: "artifact-status" }) + "\n");
      let presented: {status:string;receiptCurrent:boolean;reason:string;receipt:{status:string}} | undefined;
      const until = Date.now() + 5000;
      while (!presented) {
        for (const line of output.split("\n")) try {
          const event = JSON.parse(line); if (event.type !== "extension_ui_request" || event.method !== "notify") continue;
          const value = JSON.parse(event.message); if (value.id === job.id && typeof value.receiptCurrent === "boolean") presented = value;
        } catch {}
        if (Date.now() > until) throw new Error(output); if (!presented) await delay(20);
      }
      return presented;
    };
    for (const mode of ["missing", "corrupt"] as const) {
      if (mode === "missing") unlinkSync(artifactPath); else writeFileSync(artifactPath, "corrupted acceptance evidence");
      const presented = await query();
      for (const id of ["EVD-013", "T47"]) evidence(id, () => {
        assert.equal(presented.receiptCurrent, false); assert.equal(presented.status, "BLOCKED");
        assert.equal(presented.receipt.status, "BLOCKED"); assert.equal(presented.reason, "acceptance_artifact_missing_or_changed");
        assert.equal(requests, beforeRequests); assert.equal(store!.get<ManagedJob>("managed-jobs", job.id)!.receipt!.status, "COMPLETED");
        assert.equal(readFileSync(join(cwd, "answer.json"), "utf8"), '{"answer":1}\n');
        assert.equal(JSON.parse(readFileSync(join(job.cwd!, "answer.json"), "utf8")).answer, 2);
      });
      writeFileSync(artifactPath, saved, { mode: 0o600 });
      const restored = await query();
      for (const id of ["EVD-013", "T47"]) evidence(id, () => {
        assert.equal(restored.receiptCurrent, true); assert.equal(restored.receipt.status, "COMPLETED"); assert.equal(requests, beforeRequests);
      });
    }
  }
  if (variant === "fix") {
    const beforeRequests = requests;
    writeFileSync(join(job.cwd!, "answer.json"), '{"answer":3}\n');
    child.stdin.write(JSON.stringify({ type: "prompt", message: `/orch status ${job.id}`, id: "changed-status" }) + "\n");
    const until = Date.now() + 5000;
    while (!output.includes("receipt_invalidated_by_candidate_or_policy_change")) { if (Date.now() > until) throw new Error(output); await delay(20); }
    assert.equal(requests, beforeRequests); assert.equal(store!.get<ManagedJob>("managed-jobs", job.id)!.receipt!.snapshot, job.receipt!.snapshot);
  }
});

}
