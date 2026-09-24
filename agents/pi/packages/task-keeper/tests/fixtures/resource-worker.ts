import { processIdentity } from "../../src/adapters/process-identity.ts";
import { sharedWriteResources } from "../../src/workspace/shared-resources.ts";
import { appendFileSync } from "node:fs";
import { Store } from "../../src/store/database.ts";
import { Scheduler } from "../../src/orchestration/scheduler.ts";
import { workspaceResource } from "../../src/workspace/worktree.ts";

const [root, id, mode, source] = process.argv.slice(2);
const store = new Store(root), owner = store.claimOwner(`scope-${id}`, `owner-${id}`);
const scheduler = new Scheduler(store, owner);
const resources = mode === "declared" ? sharedWriteResources({ build: { executable: process.execPath, args: [], environment: {}, timeoutMs: 1000, kind: "build", parser: "exit-code", minimumTests: 1, sharedMutableDirectories: [source] } }).build.map(resource => resource.id) : mode === "slot" ? ["host-child"] : mode === "alias" ? [workspaceResource(source)]
  : id === "a" ? ["source", "build"] : ["build", "source"];
scheduler.submit({ id, workScope: owner.scopeId, version: 1, objective: "Cross-process resource exclusion", workflow: "fix",
  required: ["check"], optional: [], allowPartial: false, policyDigest: "policy", snapshot: "tree", maxSteps: 4, maxSemanticAttempts: 1 },
[{ id: "work", role: "worker", kind: "write", dependencies: [], allowedSkippedDependencies: [], optional: false,
  resources: resources.map(id => ({ id, capacity: 1, units: 1 })) }], 0, 0);
let heartbeatSequence = 0;
process.on("message", message => {
  if (message === "heartbeat") {
    const observation = { token: owner.token, epoch: owner.epoch, identity: processIdentity(), heartbeatSequence: ++heartbeatSequence, observedAt: Date.now() };
    store.put("owner-process", owner.scopeId, observation); process.send?.({type:"heartbeat",scopeId:owner.scopeId,observation});
  }
  if (message === "go") {
    try {
      const intent = scheduler.dispatch(id, "work", "tree"); store.markSent(owner, intent.id);
      appendFileSync(source + "/effects.txt", `${id}\n`);
      process.send?.({ type: "result", acquired: true, intent: intent.id, pid: process.pid });
    } catch (error) { process.send?.({ type: "result", acquired: false, code: (error as {code?: string}).code }); }
  }
  if (message === "quit") { store.close(); process.exit(0); }
});
process.send?.({ type: "ready", pid: process.pid, resources });
