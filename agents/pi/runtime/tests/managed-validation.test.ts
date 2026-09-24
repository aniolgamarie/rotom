import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { exerciseManaged } from "../managed-validation.ts";

for (const fault of [null, "check", "review", "second-view", "fix"]) test("managed live workflow validates receipts and restores probe: " + fault, async () => {
  const root = mkdtempSync(join(tmpdir(), "managed-live-")), project = join(root, "probe"), candidate = join(root, "candidate");
  mkdirSync(project, { mode: 0o700 }); mkdirSync(candidate, { mode: 0o700 });
  writeFileSync(join(project, "code.txt"), "changed\n", { mode: 0o600 });
  writeFileSync(join(project, "agentcfg-live-project.json"), JSON.stringify({ schema_version: 1, kind: "agentcfg-live-managed" }), { mode: 0o600 });
  writeFileSync(join(candidate, "code.txt"), fault === "fix" ? "bad\n" : "changed\n", { mode: 0o644 });
  const jobs = [], commands = [], session = { messages: [], extensionRunner: null };
  const command = { handler: async text => {
    commands.push(text);
    session.messages.push({ role: "custom", customType: "task-keeper:status", details: {} });
    if (text.startsWith("stop")) return;
    const fixing = text.startsWith("fix");
    assert.equal(readFileSync(join(project, "code.txt"), "utf8"), fixing ? "original\n" : "changed\n");
    jobs.push({ id: "job-" + jobs.length, status: "COMPLETED", cwd: candidate, snapshot: "snap", receipt: { snapshot: "snap", specVersion: 1 },
      checks: [{ checkId: "test", source: "verifier", snapshot: fault === "check" ? "old" : "snap", status: "passed", artifactId: "check" },
        { checkId: fixing ? "independent-review" : "scope-evidence-review", source: "reviewer", snapshot: "snap", specVersion: 1,
          status: fault === "review" ? "failed" : "passed", artifactId: "review" }], secondOpinion: { agreementCurrent: fault !== "second-view" } });
  } };
  session.extensionRunner = { createContext: () => ({}), createCommandContext: () => ({}), getCommand: () => command,
    getToolDefinition: () => ({ execute: async (_id, params) => ({ details: params.jobId ? jobs.find(row => row.id === params.jobId) : jobs }) }) };
  const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1"), managerKey = Symbol.for("agentcfg.pi.managed.v1");
  globalThis[runtimeKey] = { manifest: { options: { task_keeper: { check_ids: ["test"] } } } };
  globalThis[managerKey] = { manager: { hasRunning: () => false } };
  try {
    const run = () => exerciseManaged({ session }, { project, variant: "second-view" });
    if (fault) await assert.rejects(run(), /SERVICE_VALIDATION_/);
    else { const facts = await run(); assert.equal(facts.job_count, 2); assert.equal(facts.second_view_verified, true); }
    assert.equal(readFileSync(join(project, "code.txt"), "utf8"), "changed\n");
    assert.ok(commands[0].startsWith("inspect"));
  } finally { delete globalThis[runtimeKey]; delete globalThis[managerKey]; rmSync(root, { recursive: true, force: true }); }
});
