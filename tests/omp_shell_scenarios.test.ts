import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { join } from "node:path";
import { readCorpusFile } from "../scripts/check-omp-command-history";
import { evaluatePublicScenarios } from "../scripts/check-omp-shell-scenarios";
import { parseGenericCommands, matchesNativePattern, hasUncertainPatternMatch } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";

test("every rebuilt history scenario matches the independent static parse or conservative boundary", () => {
  const data = readCorpusFile(join(import.meta.dir, "fixtures/omp/command-scenarios/corpus.json.gz")) as any;
  expect(data.schemaVersion).toBe(1);
  expect(data.publication).toBe("synthetic-public");
  expect(data.oracleVersion).toBe(1);
  expect(data.records.length).toBe(data.summary.publicCases);
  expect(data.records.reduce((n: number, r: any) => n+r.representedScenarios, 0)).toBe(11504);
  expect(new Set(data.records.map((r: any) => r.id)).size).toBe(data.records.length);
  const mismatches: string[] = [];
  for (const row of data.records) {
    expect(createHash("sha256").update(row.command).digest("hex")).toBe(row.id);
    if (!isDeepStrictEqual(parseGenericCommands(row.command), row.expected)) mismatches.push(row.id);
  }
  expect({ count: mismatches.length, first: mismatches.slice(0, 10) }).toEqual({ count: 0, first: [] });
  expect(evaluatePublicScenarios(data)).toMatchObject({ cases: data.summary.publicCases, representedScenarios: 11504, mismatches: 0, thrown: 0, passed: true });
});

test("public checker rejects inconsistent metadata and reports oracle regressions", () => {
  const command = "pwd";
  const fixture = { schemaVersion: 1, publication: "synthetic-public", oracleVersion: 1, records: [{
    id: createHash("sha256").update(command).digest("hex"), command, category: "simple", features: [], representedScenarios: 1,
    expectedGate: "model", expected: { status: "complete", commands: [{ connector: "start", argv: ["pwd"] }] },
  }], summary: { inputScenarios: 1, publicCases: 1, mergedRebuiltCases: 0, representedScenarios: 1, categories: { simple: 1 }, expectedComplete: 1, expectedUnsupported: 0 } };
  expect(evaluatePublicScenarios(fixture).passed).toBe(true);
  expect(() => evaluatePublicScenarios({ ...fixture, summary: { ...fixture.summary, inputScenarios: 2 } })).toThrow();
  expect(evaluatePublicScenarios({ ...fixture, records: [{ ...fixture.records[0], expected: { status: "complete", commands: [{ connector: "start", argv: ["wrong"] }] } }] }).passed).toBe(false);
});

test("redirection effects and wildcard uncertainty cannot disappear from native protection", () => {
  const result = parseGenericCommands("echo ok > protected.txt; rm -rf target");
  expect(result.status).toBe("complete");
  if (result.status !== "complete") throw new Error("fixture parse failed");
  expect(matchesNativePattern(result.commands[0], "echo * > protected.txt")).toBe(true);
  expect(matchesNativePattern(result.commands[1], "rm *")).toBe(true);
  const glob = parseGenericCommands("cat *.txt");
  if (glob.status !== "complete") throw new Error("glob fixture parse failed");
  expect(hasUncertainPatternMatch(glob.commands[0], "cat protected.txt")).toBe(true);
  expect(hasUncertainPatternMatch(glob.commands[0], "rm *")).toBe(false);
});

test("quotes, comments, continuation and truncation have fixed independent anchors", () => {
  for (const command of ["echo a \\\nb", "echo a \\\n# hidden\n echo b"]) {
    expect(parseGenericCommands(command)).toEqual(command.includes("hidden") ? { status: "complete", commands: [
      { connector: "start", argv: ["echo", "a"] }, { connector: ";", argv: ["echo", "b"] },
    ] } : { status: "complete", commands: [{ connector: "start", argv: ["echo", "a", "b"] }] });
  }
  for (const command of ["echo $(id)", "if ls; then pwd; fi", "cat <<EOF\na\nEOF", "sudo sh -c 'rm -rf /'", "trap 'rm -rf /' EXIT", "alias x='rm -rf /'; x", "echo a >", "echo a &&", "echo a\r\nb"]) {
    expect(parseGenericCommands(command)).toEqual({ status: "unsupported", reason: "unsupported-syntax" });
  }
  expect(parseGenericCommands("echo a &&\n# note\nls")).toEqual({ status: "complete", commands: [
    { connector: "start", argv: ["echo", "a"] }, { connector: "&&", argv: ["ls"] },
  ] });
});
