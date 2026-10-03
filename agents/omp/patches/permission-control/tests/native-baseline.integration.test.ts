import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Settings } from "../src/config/settings";
import { BashTool } from "../src/tools/bash";
import { resolveApproval } from "../src/tools/approval";

/** 同一固定集只调用真实原生approval纯函数，绝不调用tool.execute。 */
test("measure native kernel approval baseline without running any fixture command", () => {
  const input = JSON.parse(readFileSync(resolve(import.meta.dir, "../../../permission-test-fixtures/baseline-input.json"), "utf8"));
  const settings = Settings.isolated({ ...input.settings, shellPath: "/bin/bash" } as never);
  const tool = new BashTool({ cwd: "/virtual/repository", settings,
    getSessionFile: () => null } as never);
  const counts: Record<string, Record<string, number>> = {};
  const results = [];
  for (const item of input.cases) {
    if (item.action.kind !== "bash") continue;
    const result = resolveApproval(tool, { command: item.action.command }, input.settings["tools.approvalMode"],
      input.settings["tools.approval"]);
    expect(["allow", "prompt", "deny"]).toContain(result.policy);
    const category = counts[item.category] ??= { allow: 0, prompt: 0, deny: 0, compoundPrompt: 0 };
    category[result.policy]++;
    if (item.action.compound && result.policy === "prompt") category.compoundPrompt++;
    results.push({ id: item.id, policy: result.policy });
  }
  expect(results).toHaveLength(200);
  expect(counts).toEqual(input.measuredCounts);
  expect(results).toEqual(input.measuredResults);
  const counters = (globalThis as any).__ompBridgeNativeMock;
  for (const key of ["shellConstruct", "shellRun", "process", "worker", "network", "mkdir", "snapshot", "envLoad", "service", "job"])
    expect(counters[key]).toBe(0);
  console.log("PERMISSION_NATIVE_BASELINE=" + JSON.stringify({ schemaVersion: 1,
    scope: "native-approval-functions-only; no-host-or-command-execution", fixtureDigest: input.fixtureDigest,
    recipeDigest: input.recipeDigest, stateSequenceCases: "not-applicable", commandExecutions: 0, counts, results }));
});
