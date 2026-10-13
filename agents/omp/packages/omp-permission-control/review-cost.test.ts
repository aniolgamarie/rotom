import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { baseConfig, fakeHost, ready } from "./standalone-fixture";
import { validateStandaloneConfig } from "./standalone";
import { checkConfiguredRules, reviewConfiguredRules } from "./standalone-policy";

test("compact rules preserve every restriction and original local rule identity", () => {
  const rules = [
    { match: "ls *", approval: "allow" },
    { match: "rm *", approval: "deny" },
    { match: "git push *", approval: "prompt" },
    { match: "cat /private/*", approval: "deny" },
  ] as const;
  const mutable = rules.map(rule => ({ ...rule }));
  expect(reviewConfiguredRules(mutable)).toEqual({ deny: ["rm *", "cat /private/*"], prompt: ["git push *"] });
  expect(checkConfiguredRules("rm one", mutable).matchedRuleIds).toEqual([1]);
  expect(checkConfiguredRules("git push origin", mutable).decision).toBe("prompt");
  expect(reviewConfiguredRules([{ match: "*", approval: "allow" }])).toBeUndefined();
  expect(mutable).toEqual(rules);
});

test("real profile compact representation reduces bytes while retaining every deny and prompt", () => {
  const profile = Bun.TOML.parse(readFileSync(join(import.meta.dir, "../../../../profiles/omp-kernel.toml"), "utf8")) as any;
  const rules = profile.agent_options.runtime.bash.patterns;
  const compact = reviewConfiguredRules(rules)!;
  expect(compact.deny).toEqual(rules.filter((rule: any) => rule.approval === "deny").map((rule: any) => rule.match));
  expect(compact.prompt).toEqual(rules.filter((rule: any) => rule.approval === "prompt").map((rule: any) => rule.match));
  const previous = rules.map((rule: any, id: number) => ({ id, ...rule, uncertain: false }));
  expect(Buffer.byteLength(JSON.stringify(compact))).toBeLessThan(Buffer.byteLength(JSON.stringify(previous)) / 2);
  expect(profile.agent_options.permission_control.review_max_output_tokens).toBe(2048);
});

test("raw entrypoint keeps full command, user restrictions and model coverage with compact rules", async () => {
  const command = "printf '%s' unchanged";
  const h = await fakeHost({ config: { ...baseConfig, reviewMaxOutputTokens: 2048, nativePatterns: [
    { match: "*", approval: "allow" }, { match: "rm *", approval: "deny" }, { match: "git push *", approval: "prompt" },
  ] }, messages: [{ type: "message", message: { role: "user", content: "先备份，只允许处理本项目" } }] });
  const result = await (await ready(h)).execute("cost-call", { command }, undefined, undefined, h.ctx);
  expect(result.isError).not.toBe(true);
  expect(h.fetchCalls).toHaveLength(1); expect(h.execCalls).toHaveLength(1);
  const request = JSON.parse(h.fetchCalls[0][1].body);
  const packet = JSON.parse(request.messages.at(-1).content);
  expect(request.max_tokens).toBe(2048);
  expect(packet.command).toBe(command);
  expect(packet.genuineUserMessages).toEqual(["先备份，只允许处理本项目"]);
  expect(packet.executionContext.configuredRules).toEqual({ deny: ["rm *"], prompt: ["git push *"] });
});

test("usage from a truncated primary and valid fallback reaches per-attempt audit and status", async () => {
  let calls = 0;
  const h = await fakeHost({ config: { ...baseConfig, reviewMaxOutputTokens: 2048,
    remoteFallback: { provider: "remote", model: "fallback" } }, fetchImpl: async (_url, init) => {
    expect(JSON.parse(init.body as string).max_tokens).toBe(2048);
    calls++;
    return new Response(JSON.stringify(calls === 1 ? { choices: [{ finish_reason: "length", message: { content: "" } }],
      usage: { prompt_tokens: 800, completion_tokens: 2048, prompt_tokens_details: { cached_tokens: 300 } } } :
      { choices: [{ message: { content: JSON.stringify({ decision: "allow", risk: "low", authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" }) } }],
        usage: { prompt_tokens: 800, completion_tokens: 50 } }));
  } });
  await (await ready(h)).execute("usage-call", { command: "ls" }, undefined, undefined, h.ctx);
  expect(h.execCalls).toHaveLength(1);
  const attempts = h.auditEntries.at(-1)!.data.attempts;
  expect(attempts[0]).toMatchObject({ failureCode: "REVIEW_OUTPUT_TRUNCATED",
    usage: { inputTokens: 800, outputTokens: 2048, cacheReadTokens: 300 } });
  expect(attempts[1]).toMatchObject({ decision: "allow", usage: { inputTokens: 800, outputTokens: 50 } });
  await h.commands.get("permission-control").handler("status", h.ctx);
  const status = JSON.parse(h.notices.at(-1)!);
  expect(status.reviewMaxOutputTokens).toBe(2048);
  expect(status.primary.usage).toEqual({ inputTokens: 800, outputTokens: 2048, cacheReadTokens: 300 });
  expect(status.remote.usage).toEqual({ inputTokens: 800, outputTokens: 50 });
});

test("native output configuration remains optional and rejects wrong values and unknown fields", () => {
  expect(validateStandaloneConfig(baseConfig)).toEqual(baseConfig);
  for (const value of [255, 8193, true, null, "2048", 2048.5])
    expect(() => validateStandaloneConfig({ ...baseConfig, reviewMaxOutputTokens: value })).toThrow();
  expect(() => validateStandaloneConfig({ ...baseConfig, outputTokenTypo: 2048 })).toThrow();
});
