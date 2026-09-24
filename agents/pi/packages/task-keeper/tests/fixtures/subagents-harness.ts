import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { dirname, basename, join } from "node:path";
import { writeFileSync, renameSync, readdirSync, unlinkSync, watch, existsSync, mkdirSync } from "node:fs";
import { readConfig } from "../../src/config.ts";
import { Store } from "../../src/store/database.ts";
import { SubagentsAdapter } from "../../src/adapters/subagents.ts";
import { newId } from "../../src/contracts/primitives.ts";

// Existence is the reader's completion barrier, so publish only complete JSON.
function publishResult(root: string, body: string) {
  const path = join(root, "adapter-result.json"), temporary = `${path}.${newId("publish")}`;
  writeFileSync(temporary, body); renameSync(temporary, path);
}

export default function harness(pi: ExtensionAPI) {
  pi.registerCommand("tk-delegate", {
    description: "Isolated adapter contract fixture",
    handler: async (args, ctx) => {
      const config = readConfig(process.env.PI_TASK_KEEPER_CONFIG!);
      const store = new Store(dirname(config.storage.path), basename(config.storage.path));
      const owner = store.claimOwner("harness-parent", newId("owner"));
      let removeFaultObserver = () => {};
      try {
        if (args.trim() === "duplicate-controller") {
          const replies: unknown[] = []; let extraOwnerReply = false;
          const removeReady = pi.events.on("subagent:recovery-owner-ready", (reply: unknown) => {
            replies.push(reply); writeFileSync(join(store.root, "duplicate-controller.json"), JSON.stringify({ extraOwnerReply, replies }));
          });
          const removeProbe = pi.events.on("subagent:recovery-owner-probe", (value: unknown) => {
            const probe = value as { id: string }; extraOwnerReply = true;
            pi.events.emit("subagent:recovery-owner-ready", { id: probe.id, version: "task-keeper-recovery-owner-v2",
              entry: new URL("../../node_modules/pi-subagents/index.ts", import.meta.url).href });
          });
          removeFaultObserver = () => { removeProbe(); removeReady(); };
        }
        if (args.trim() === "verify-stress") {
          const { runVerification } = await import("../../src/verification/runner.ts");
          const results = [];
          for (let i = 0; i < 100; i++) {
            const result = await runVerification("build", { build: { executable: process.execPath, args: ["-e", "process.exit(0)"], environment: {}, timeoutMs: 5000,
              kind: "build", parser: "exit-code", minimumTests: 1 } }, { cwd: ctx.cwd, jobId: "stress", snapshot: "snapshot" });
            results.push(result);
            if (result.status !== "passed") break;
          }
          publishResult(store.root, JSON.stringify({ results })); return;
        }
        if (args.trim() === "parent-helper") {
          const scope = await import("pi-subagents/recovery-owner");
          if (scope.recoveryOwnerVersion !== "task-keeper-recovery-owner-v2" || !scope.recoveryOwnerGateHealthy()) throw new Error("Owned helper gate unavailable");
          const request = () => ctx.modelRegistry.complete(ctx.model!, { messages: [{ role: "user", content: "Synthetic auxiliary summary", timestamp: Date.now() }], tools: [] }, { maxTokens: 16 });
          let blocked = false, reason = "", denied = 0;
          try { const result = await scope.withRecoveryOwner(request, () => { denied++; }); blocked = result.stopReason === "error" || result.stopReason === "aborted"; reason = result.errorMessage ?? ""; }
          catch (error) { blocked = true; reason = String(error); }
          const ordinary = await request();
          publishResult(store.root, JSON.stringify({ blocked, reason, denied, ordinary: ordinary.stopReason })); return;
        }
        if (args.trim() === "protected-gate-unavailable") {
          const scope = await import("pi-subagents/recovery-owner"), original = globalThis.fetch;
          // A real unknown wrapper removes the certified fetch-chain identity.
          globalThis.fetch = (...parameters) => original(...parameters);
          try {
            let reason = "", completed = false;
            try { await new SubagentsAdapter(pi,store,config,owner).execute({jobId:"job-fixture",stepId:"step-fixture",role:"worker",task:"Must not dispatch without a reliable gate",cwd:ctx.cwd},ctx);completed=true; }
            catch(error){reason=error instanceof Error?error.message:String(error);}
            const ordinary=await ctx.modelRegistry.complete(ctx.model!,{messages:[{role:"user",content:"Independent unprotected availability witness",timestamp:Date.now()}],tools:[]},{maxTokens:16});
            publishResult(store.root,JSON.stringify({gateHealthy:scope.recoveryOwnerGateHealthy(),completed,reason,ordinary:ordinary.stopReason,
              grants:store.list("child-grants"),observations:store.list("child-observations"),requests:store.db.prepare("SELECT * FROM requests").all(),claims:store.claims()}));
          } finally {globalThis.fetch=original;}
          return;
        }
        const adapter = new SubagentsAdapter(pi, store, config, owner), cancellation = new AbortController();
        if (["race-work-budget", "protected-race"].includes(args.trim())) {
          const results = await Promise.all(["a", "b"].map(async label => {
            const cwd = join(ctx.cwd, `child-${label}`); mkdirSync(cwd, { recursive: true });
            return adapter.execute({ jobId: `job-${label}`, stepId: "step", role: "worker", task: `Budget race child ${label}. Respond without tools.`, cwd }, ctx);
          }));
          publishResult(store.root, JSON.stringify({ results })); return;
        }
        let dispatchGuard: (() => void) | undefined;
        if (args.trim() === "cancel-find") {
          const marker = join(ctx.cwd, "find-ready.json");
          const watcher = watch(ctx.cwd, () => { if (existsSync(marker)) cancellation.abort(); });
          removeFaultObserver = () => watcher.close();
        }
        if (args.trim() === "cancel-preflight") {
          const preflight = adapter.preflight.bind(adapter);
          adapter.preflight = async (...parameters: Parameters<typeof preflight>) => { const result = await preflight(...parameters); cancellation.abort(); return result; };
        }
        if (args.trim() === "cancel-dispatch") dispatchGuard = () => cancellation.abort();
        if (args.trim() === "async-dispatch") dispatchGuard = async () => {};
        if (["cancel-preflight", "cancel-dispatch", "async-dispatch"].includes(args.trim())) {
          let dispatched = 0;
          removeFaultObserver = pi.events.on("prompt-template:subagent:request", () => { dispatched++; writeFileSync(join(store.root, "unexpected-dispatch.json"), JSON.stringify({ dispatched })); });
        }
        if (args.trim() === "lost-observations") removeFaultObserver = pi.events.on("prompt-template:subagent:response", (data: unknown) => {
          const response = data as { requestId: string; ownerRunId: string; status: string; exitCode: number };
          if (response.ownerRunId !== "job-fixture") return;
          const observations = store.list<{ descriptorId: string; producerId: string; ready: boolean; leaseId: string; toolErrors: unknown[] }>("child-observations").filter(row => row.value.descriptorId === response.requestId);
          writeFileSync(join(store.root, "lost-observation-witness.json"), JSON.stringify({ nativeStatus: response.status, exitCode: response.exitCode,
            toolErrors: observations.flatMap(row => row.value.toolErrors), reporters: observations.map(row => ({ready:row.value.ready,producerId:row.value.producerId,leaseId:row.value.leaseId})) }));
          for (const row of observations) {
            store.db.prepare("DELETE FROM events WHERE producer=?").run(row.value.producerId);
            store.db.prepare("DELETE FROM records WHERE namespace=? AND id=?").run("child-observations", row.id);
          }
        });
        if (args.trim() === "broken-channel") {
          removeFaultObserver = pi.events.on("prompt-template:subagent:response", (value:unknown) => {
            const response=value as Record<string,unknown>;
            if(response.ownerRunId === "job-fixture")writeFileSync(join(store.root,"broken-channel-witness.json"),JSON.stringify(response));
          });
          const preflight = adapter.preflight.bind(adapter);
          adapter.preflight = async (...parameters: Parameters<typeof preflight>) => {
            const result = await preflight(...parameters);
            const directory = join(store.root, "child-contexts");
            for (const file of readdirSync(directory)) unlinkSync(join(directory, file));
            return result;
          };
        }
        const result = await adapter.execute({ jobId: "job-fixture", stepId: "step-fixture", role: args.trim() === "scout" ? "scout" : "worker",
          task: "Perform the synthetic bounded adapter fixture task." + (args.trim() === "compaction" ? " Historical synthetic context. ".repeat(2000) : ""), cwd: ctx.cwd }, ctx, cancellation.signal, dispatchGuard);
        publishResult(store.root, JSON.stringify(result));
      } catch (error) {
        publishResult(store.root, JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
      } finally { removeFaultObserver(); store.revokeOwner(owner); store.close(); }
    },
  });
}
