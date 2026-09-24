import { spawn } from "node:child_process";
import { once } from "node:events";
import { createHash } from "node:crypto";
import { createServer, type ServerResponse } from "node:http";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, readlinkSync, renameSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { Config } from "../../src/config.ts";
import type { ManagedJob } from "../../src/orchestration/service.ts";
import { Store } from "../../src/store/database.ts";
import { processIdentity, originalProcessStopped } from "../../src/adapters/process-identity.ts";
import { workspaceResource } from "../../src/workspace/worktree.ts";
import { assert, evidence, acceptance, observerArtifact } from "../recorded-test.ts";
import { listenLoopback } from "../helpers.ts";

export function verifierWorkspaceCut(source: string, root: string) {
  const copy = join(root, "verifier-workspace-cut-package"); mkdirSync(copy);
  for (const file of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(source, file), join(copy, file), { recursive: true });
  mkdirSync(join(copy, "tests/fixtures"), { recursive: true });
  cpSync(join(source, "tests/fixtures/subagents-harness.ts"), join(copy, "tests/fixtures/subagents-harness.ts"));
  symlinkSync(join(source, "node_modules"), join(copy, "node_modules"));
  const path = join(copy, "src/orchestration/workflow-plan.ts"), original = readFileSync(path, "utf8");
  const needle = ", { id: workspaceLock, capacity: 1, units: 1 }";
  if (original.split(needle).length !== 3) throw new Error("Verifier workspace cut must match exactly baseline and candidate demands");
  const mutated = original.replaceAll(needle, ""); writeFileSync(path, mutated);
  const sha256 = (text: string) => createHash("sha256").update(text).digest("hex");
  writeFileSync(join(root, "verifier-workspace-cut-manifest.json"), JSON.stringify({ path, needle, replacements: 2,
    original: sha256(original), mutated: sha256(mutated) }, null, 2));
  return copy;
}

export function holdCandidateVerifier(config: Config, root: string) {
  const binding = config.verificationBindings["focused-tests"], original = binding.args[1];
  binding.timeoutMs = 40000;
  binding.args = ["-e", `const fs=require('node:fs');fs.writeFileSync(${JSON.stringify(join(root, "freeze-ready.tmp"))},JSON.stringify({pid:process.pid,cwd:process.cwd(),namespace:fs.readlinkSync('/proc/self/ns/pid'),stat:fs.readFileSync('/proc/self/stat','utf8')}));fs.renameSync(${JSON.stringify(join(root, "freeze-ready.tmp"))},${JSON.stringify(join(root, "freeze-ready.json"))});const timer=setInterval(()=>{if(fs.existsSync(${JSON.stringify(join(root, "freeze-release"))})){clearInterval(timer);${original}}},10);`];
}

// Both the unchanged and demand-cut workflow run this exact byte/tool oracle.
function frozenSourceOracle(before: Buffer, after: Buffer, successfulWrites: number) {
  assert.deepEqual(after, before, "SCH010_FREEZE_ZERO_WRITES: candidate bytes changed while verifier held");
  assert.equal(successfulWrites, 0, "SCH010_FREEZE_ZERO_WRITES: successful writer tool during verification");
}

export async function contendWithCandidateVerifier(input: { root: string; sourcePkg: string; agentDir: string; configPath: string; job: ManagedJob; store: Store }) {
  const { root, sourcePkg, agentDir, configPath, job, store } = input;
  const candidate = job.cwd!, source = join(candidate, "answer.json"), before = readFileSync(source);
  const ready = JSON.parse(readFileSync(join(root, "freeze-ready.json"), "utf8"));
  const verifierPid = readdirSync("/proc").filter(id => /^\d+$/.test(id)).find(id => {
    try { return readlinkSync(`/proc/${id}/ns/pid`) === ready.namespace
      && Number(/^NSpid:\s+(.+)$/m.exec(readFileSync(`/proc/${id}/status`, "utf8"))?.[1].trim().split(/\s+/).at(-1)) === ready.pid; } catch { return false; }
  });
  assert.ok(verifierPid, "real supervised verifier must be alive");
  const verifierIdentity = processIdentity(Number(verifierPid))!;
  assert.ok(verifierIdentity); assert.equal(originalProcessStopped(verifierIdentity), false);
  assert.equal(ready.cwd, candidate);
  assert.equal(ready.stat.slice(ready.stat.lastIndexOf(")") + 2).trim().split(/\s+/)[19], verifierIdentity.startTicks);
  const step = store.get<{ steps: Array<{ id: string; status: string; intentId: string; resources: unknown[] }> }>("jobs", job.id)!.steps.find(step => step.id === "focused-tests")!;
  const resource = `writer-${workspaceResource(candidate)}`;
  const claimsBefore = store.claims(), verifierIntent = store.intent(step.intentId)!;
  assert.equal(step.status, "running"); assert.equal(verifierIntent.status, "sent");
  // Do not short-circuit the mutation on the missing demand: it must reach the physical write oracle.
  if (!process.env.TASK_KEEPER_SCH010_CUT) assert.ok(claimsBefore.some(claim => claim.resource_id === resource && claim.intent_id === step.intentId));
  const competitorAgent = join(root, "competitor-agent"); mkdirSync(competitorAgent);
  const receiver: unknown[] = []; let successfulWrites = 0;
  const reply = (res: ServerResponse, tool: boolean) => {
    res.writeHead(200, { "content-type": "text/event-stream" });
    const delta = tool ? { role: "assistant", tool_calls: [{ index: 0, id: "freeze-write", type: "function", function: { name: "tk_write", arguments: JSON.stringify({ path: "answer.json", content: '{"answer":3}\n' }) } }] }
      : { role: "assistant", content: "Bounded contention writer completed." };
    for (const choice of [{ index: 0, delta, finish_reason: null }, { index: 0, delta: {}, finish_reason: tool ? "tool_calls" : "stop" }]) res.write(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", created: 1, model: "fixture-model", choices: [choice] })}\n\n`);
    res.end("data: [DONE]\n\n");
  };
  const server = createServer((req, res) => {
    let body = ""; req.on("data", chunk => { body += chunk; }); req.on("end", () => {
      const request = JSON.parse(body); receiver.push(request);
      const tools = request.messages.filter((message: {role: string}) => message.role === "tool");
      if (tools.some((message: {tool_call_id: string; content: string}) => message.tool_call_id === "freeze-write"
        && message.content === `Successfully wrote 13 bytes to ${source}`)) successfulWrites++;
      reply(res, !tools.length);
    });
  });
  const port = await listenLoopback(server);
  const models = JSON.parse(readFileSync(join(agentDir, "models.json"), "utf8"));
  models.providers["fixture-provider"].baseUrl = `http://127.0.0.1:${port}/v1`;
  writeFileSync(join(competitorAgent, "models.json"), JSON.stringify(models));
  cpSync(join(agentDir, "settings.json"), join(competitorAgent, "settings.json"));
  const writer = spawn(process.execPath, [join(sourcePkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"), "--mode", "rpc", "--no-extensions",
    "-e", join(sourcePkg, "node_modules/pi-subagents/index.ts"), "-e", join(sourcePkg, "tests/fixtures/subagents-harness.ts"),
    "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline", "--provider", "fixture-provider", "--model", "fixture-model", "--thinking", "off", "--no-tools", "--session-dir", join(root, "competitor-sessions")],
    { cwd: candidate, stdio: ["pipe", "pipe", "pipe"], env: { PATH: `${join(sourcePkg, "node_modules/.bin")}:${process.env.PATH}`, LANG: "C.UTF-8", PI_CODING_AGENT_DIR: competitorAgent,
      PI_TASK_KEEPER_CONFIG: configPath, PI_SUBAGENTS_TEMP_ROOT: join(root, "competitor-native"), PI_MODEL_EXCLUSIONS_PATH: join(root, "competitor-exclusions.json"), PI_OFFLINE: "1", PI_TELEMETRY: "0" } });
  let output = "", errors = ""; writer.stdout.on("data", data => { output += data; }); writer.stderr.on("data", data => { errors += data; });
  const witness: Record<string, unknown> = { ready, verifierIdentity, writerParent: processIdentity(writer.pid), resource, step, verifierIntent, claimsBefore, before: before.toString("base64") };
  const save = () => writeFileSync(join(root, "freeze-observer.json"), JSON.stringify({ ...witness, receiver, successfulWrites, output, errors }, null, 2));
  const attempt = async (label: string) => {
    writer.stdin.write(JSON.stringify({ id: label, type: "prompt", message: "/tk-delegate worker" }) + "\n");
    const until = Date.now() + 30000, resultPath = join(store.root, "adapter-result.json");
    while (!existsSync(resultPath)) {
      if (Date.now() > until || writer.exitCode !== null || writer.signalCode !== null) throw new Error(`Writer did not finish admission: ${output}\n${errors}`);
      await delay(20);
    }
    const result = JSON.parse(readFileSync(resultPath, "utf8")); renameSync(resultPath, join(root, `${label}-result.json`));
    const descriptors = readdirSync(join(store.root, "child-contexts")).map(file => JSON.parse(readFileSync(join(store.root, "child-contexts", file), "utf8"))).filter(value => value.jobId === "job-fixture");
    witness[label] = { result, descriptors, claims: store.claims(), observations: store.list("child-observations") }; save();
    assert.ok(descriptors.length, "real adapter must create a descriptor and dispatch");
    assert.ok(descriptors.every(value => value.cwd === candidate && value.owner.scopeId !== verifierIntent.scopeId));
    return result;
  };
  try {
    const blocked = await attempt("frozen-attempt");
    assert.equal(originalProcessStopped(verifierIdentity), false); assert.equal(existsSync(join(root, "freeze-release")), false);
    witness.frozenBytes = readFileSync(source).toString("base64"); save();
    for (const id of ["SCH-010", "TK06"]) evidence(id, () => frozenSourceOracle(before, readFileSync(source), successfulWrites));
    assert.equal(blocked.status, "failed"); assert.equal(blocked.terminationConfirmed, true);
    assert.ok(blocked.nativeRunId, "denial must come from a real native writer, not parent preflight");
    assert.equal(blocked.error, resource, "native resource denial must name the verifier's exact writer-workspace claim");
    assert.equal(receiver.length, 0, "denied native writer must not send model requests");
    assert.ok(store.claims().some(claim => claim.resource_id === resource && claim.intent_id === step.intentId));
    writeFileSync(join(root, "freeze-release"), "release real verifier");
    const until = Date.now() + 10000;
    while (originalProcessStopped(verifierIdentity) !== true || store.claims().some(claim => claim.intent_id === step.intentId)) {
      if (Date.now() > until) throw new Error("Verifier did not physically terminate and release claims"); await delay(20);
    }
    witness.releasedIntent = store.intent(step.intentId); witness.releasedClaims = store.claims(); save();
    const progressed = await attempt("released-attempt");
    for (const id of ["SCH-010", "TK06"]) evidence(id, () => {
      assert.equal(progressed.status, "ended"); assert.equal(progressed.terminationConfirmed, true);
      assert.equal(readFileSync(source, "utf8"), '{"answer":3}\n'); assert.equal(successfulWrites, 1);
      assert.ok(progressed.observations.some((observation: {toolErrors: unknown[]}) => observation.toolErrors.length === 0));
    });
    witness.after = readFileSync(source).toString("base64"); save();
    acceptance("AC28","verifier-freeze",{level:"P",observer:"live-verifier-PID-competing-native-writer-and-candidate-bytes",predicate:"writer blocked until verifier physically stopped",artifact:observerArtifact("verifier-freeze",witness)},()=>{assert.equal(blocked.status,"failed");assert.equal(blocked.error,resource);assert.equal(progressed.status,"ended");assert.equal(successfulWrites,1);assert.equal(originalProcessStopped(verifierIdentity),true);assert.equal(readFileSync(source,"utf8"),'{"answer":3}\n');});

  } finally {
    writeFileSync(join(root, "freeze-release"), "cleanup verifier barrier");
    if (writer.exitCode === null && writer.signalCode === null) { const exit = once(writer, "exit"); writer.kill("SIGTERM"); await exit; }
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); save();
  }
}
