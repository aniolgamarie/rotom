import { expect, test } from "bun:test";
import scenarios from "./fixtures/omp/command-scenarios/strict-acceptance.json";
import { parseGenericCommands, matchesNativePattern, hasUncertainPatternMatch } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";

// 预期手工按公开静态语法填写；不从解析器或历史数据重建 oracle。
test("strict acceptance scenarios have distinct IDs and explicit language reasons", () => {
  expect(scenarios.oracle).toBe("independent-handwritten-static-contract");
  expect(new Set(scenarios.complete.map(row => row.id)).size).toBe(scenarios.complete.length);
  expect(new Set(scenarios.manual.map(row => row.id)).size).toBe(scenarios.manual.length);
  for (const row of [...scenarios.complete, ...scenarios.manual]) {
    expect(row.reason.length).toBeGreaterThan(12);
  }
  expect(scenarios.complete.filter(row => row.gate === "model-eligible").length).toBeGreaterThanOrEqual(15);
  expect(scenarios.manual.length).toBeGreaterThanOrEqual(30);
});

for (const row of scenarios.complete) {
  test(`strict complete structure: ${row.id} (${row.gate})`, () => {
    // 深比较同时检查 argv、connector、HOME/glob下标和重定向顺序，无需真实shell。
    expect(parseGenericCommands(row.command)).toEqual({ status: "complete", commands: row.commands });
  });
}

for (const row of scenarios.manual) {
  test(`strict manual boundary standalone and compound: ${row.id}`, () => {
    // 同一不支持结构不能因前后添加普通命令而被静态审批放行。
    for (const command of [row.command, `pwd && ${row.command}`, `${row.command}; echo done`, `command -v ob | ${row.command}`]) {
      expect(parseGenericCommands(command)).toEqual({ status: "unsupported", reason: "unsupported-syntax" });
    }
  });
}

test("complete dangerous compounds retain every protected native effect", () => {
  for (const row of scenarios.complete.filter(row => row.gate === "native-protection-required")) {
    const parsed = parseGenericCommands(row.command);
    if (parsed.status !== "complete") throw new Error(`Expected complete fixture: ${row.id}`);
    expect(parsed.commands.some(command => matchesNativePattern(command, "rm *"))).toBe(true);
  }
  const write = parseGenericCommands("command -v ob && echo ok 2>&1 > protected.txt; rm -rf ~/private");
  if (write.status !== "complete") throw new Error("Expected complete protected write fixture");
  expect(matchesNativePattern(write.commands[1], "echo * > protected.txt")).toBe(true);
  expect(matchesNativePattern(write.commands[2], "rm *")).toBe(true);
  expect(hasUncertainPatternMatch(write.commands[2], "rm /resolved/private")).toBe(true);
});

test("HOME and unquoted glob uncertainty remain distinct from quoted literal data", () => {
  const parsed = parseGenericCommands("cat ~/notes/*.txt && cat '~/notes/*.txt' && cat \\~/notes/\\*.txt");
  if (parsed.status !== "complete") throw new Error("Expected complete uncertainty fixture");
  expect(hasUncertainPatternMatch(parsed.commands[0], "cat /resolved/private.txt")).toBe(true);
  expect(hasUncertainPatternMatch(parsed.commands[1], "cat /resolved/private.txt")).toBe(false);
  expect(hasUncertainPatternMatch(parsed.commands[2], "cat /resolved/private.txt")).toBe(false);
  expect(hasUncertainPatternMatch(parsed.commands[0], "rm /resolved/private.txt")).toBe(false);
});

test("a tilde inside a HOME path suffix stays literal without another expansion", () => {
  // 只有参数开头~/触发HOME标记，路径中的后续~是普通文件名字符。
  expect(parseGenericCommands("ls ~/backup~ ~/notes/~draft && command -v ob")).toEqual({ status: "complete", commands: [
    { connector: "start", argv: ["ls", "~/backup~", "~/notes/~draft"], homeExpansions: [1, 2] },
    { connector: "&&", argv: ["command", "-v", "ob"] },
  ] });
});
