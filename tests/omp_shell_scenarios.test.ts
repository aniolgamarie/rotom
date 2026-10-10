import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { readCorpusFile } from "../scripts/check-omp-command-history";
import { evaluatePublicScenarios } from "../scripts/check-omp-shell-scenarios";
import { parseGenericCommands, matchesNativePattern, hasUncertainPatternMatch } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";

test("every rebuilt history scenario matches the independent static parse or conservative boundary", () => {
  const data = readCorpusFile(join(import.meta.dir, "fixtures/omp/command-scenarios/corpus.json.gz")) as any;
  const overlay = JSON.parse(readFileSync(join(import.meta.dir, "fixtures/omp/command-scenarios/grammar-parse-upgrade-20261009.json"), "utf8"));
  const status = JSON.parse(readFileSync(join(import.meta.dir, "fixtures/omp/command-scenarios/grammar-status-upgrade-20261010.json"), "utf8"));
  const upgrades = new Map<string, any>([...overlay.entries, ...status.entries].map((entry: any) => [entry.id, entry.fullParse]));
  expect(data.schemaVersion).toBe(1);
  expect(data.publication).toBe("synthetic-public");
  expect(data.oracleVersion).toBe(1);
  expect(data.records.length).toBe(data.summary.publicCases);
  expect(data.records.reduce((n: number, r: any) => n+r.representedScenarios, 0)).toBe(11504);
  expect(new Set(data.records.map((r: any) => r.id)).size).toBe(data.records.length);
  const mismatches: string[] = [];
  for (const row of data.records) {
    expect(createHash("sha256").update(row.command).digest("hex")).toBe(row.id);
    if (!isDeepStrictEqual(parseGenericCommands(row.command), upgrades.get(row.id) ?? row.expected)) mismatches.push(row.id);
  }
  expect({ count: mismatches.length, first: mismatches.slice(0, 10) }).toEqual({ count: 0, first: [] });
  expect(evaluatePublicScenarios(data, overlay, status)).toMatchObject({ cases: data.summary.publicCases, representedScenarios: 11504,
    frozenComplete: 9442, frozenUnsupported: 2031, effectiveComplete: 10090, effectiveUnsupported: 1383,
    upgradedParses: 648, mismatches: 0, thrown: 0, passed: true });
  expect(evaluatePublicScenarios(data)).toMatchObject({ frozenComplete: 9442, frozenUnsupported: 2031,
    effectiveComplete: 9442, effectiveUnsupported: 2031, upgradedParses: 0, mismatches: 648, passed: false });
});

test("fixed full-parse overlay rejects tampered sources, IDs, structures and metadata", () => {
  const data = readCorpusFile(join(import.meta.dir, "fixtures/omp/command-scenarios/corpus.json.gz")) as any;
  const original = JSON.parse(readFileSync(join(import.meta.dir, "fixtures/omp/command-scenarios/grammar-parse-upgrade-20261009.json"), "utf8"));
  for (const change of [
    (value: any) => value.entries.pop(),
    (value: any) => value.entries.push(value.entries[0]),
    (value: any) => value.entries[0].id = "0".repeat(64),
    (value: any) => value.entries[0].sourceRowSha256 = "0".repeat(64),
    (value: any) => value.entries[0].fullParse.commands[0].argv.push("changed"),
    (value: any) => value.entries[0].fullParse = { status: "complete" },
    (value: any) => value.entries[0].unexpected = true,
    (value: any) => value.counts.HOME++,
    (value: any) => value.oracleVersion = 1,
    (value: any) => value.sourceCorpusSha256 = "0".repeat(64),
    (value: any) => value.sourceCorpusCanonicalSha256 = "0".repeat(64),
    (value: any) => value.sourceOracleSha256 = "0".repeat(64),
    (value: any) => value.sourceGateOverlaySha256 = "0".repeat(64),
  ]) {
    const tampered = structuredClone(original);
    change(tampered);
    expect(() => evaluatePublicScenarios(data, tampered)).toThrow();
  }
  const tamperedRows = structuredClone(data);
  tamperedRows.records[0].expected = { status: "complete", commands: [{ connector: "start", argv: ["changed"] }] };
  expect(() => evaluatePublicScenarios(tamperedRows, original)).toThrow();
  const tamperedMetadata = structuredClone(data);
  tamperedMetadata.summary.expectedComplete++;
  expect(() => evaluatePublicScenarios(tamperedMetadata, original)).toThrow();
});

test("public checker rejects inconsistent metadata and reports oracle regressions", () => {
  const command = "pwd";
  const fixture = { schemaVersion: 1, publication: "synthetic-public", oracleVersion: 1, records: [{
    id: createHash("sha256").update(command).digest("hex"), command, category: "simple", features: [], representedScenarios: 1,
    expectedGate: "model", expected: { status: "complete", commands: [{ connector: "start", argv: ["pwd"] }] },
  }], summary: { inputScenarios: 1, publicCases: 1, mergedRebuiltCases: 0, representedScenarios: 1, categories: { simple: 1 }, expectedComplete: 1, expectedUnsupported: 0 } };
  expect(evaluatePublicScenarios(fixture)).toMatchObject({ complete: 1, unsupported: 0, frozenComplete: 1,
    frozenUnsupported: 0, effectiveComplete: 1, effectiveUnsupported: 0, upgradedParses: 0, passed: true });
  expect(() => evaluatePublicScenarios({ ...fixture, summary: { ...fixture.summary, inputScenarios: 2 } })).toThrow();
  expect(evaluatePublicScenarios({ ...fixture, records: [{ ...fixture.records[0], expected: { status: "complete", commands: [{ connector: "start", argv: ["wrong"] }] } }] }).passed).toBe(false);
  // 不在固定差量内的新语义漂移仍按独立原预期报告失败，不自动重生oracle。
  const home = "ls ~/other";
  const boundary = { ...fixture, records: [{ ...fixture.records[0], id: createHash("sha256").update(home).digest("hex"), command: home,
    expectedGate: "human", expected: { status: "unsupported", reason: "unsupported-syntax" } }],
    summary: { ...fixture.summary, expectedComplete: 0, expectedUnsupported: 1 } };
  expect(evaluatePublicScenarios(boundary)).toMatchObject({ frozenComplete: 0, frozenUnsupported: 1,
    effectiveComplete: 0, effectiveUnsupported: 1, upgradedParses: 0, mismatches: 1, passed: false });
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


test("fixed numeric status overlay rejects tampering and cannot be inferred from the current parser", () => {
  const data = readCorpusFile(join(import.meta.dir, "fixtures/omp/command-scenarios/corpus.json.gz")) as any;
  const base = JSON.parse(readFileSync(join(import.meta.dir, "fixtures/omp/command-scenarios/grammar-parse-upgrade-20261009.json"), "utf8"));
  const status = JSON.parse(readFileSync(join(import.meta.dir, "fixtures/omp/command-scenarios/grammar-status-upgrade-20261010.json"), "utf8"));
  for (const change of [
    (value: any) => value.entries.pop(), (value: any) => value.entries.push(value.entries[0]),
    (value: any) => value.entries[0].fullParse.commands[0].argv.push("changed"),
    (value: any) => value.entries[0].sourceRowSha256 = "0".repeat(64),
    (value: any) => value.sourceOracleSha256 = "0".repeat(64),
    (value: any) => value.count++, (value: any) => value.unexpected = true,
  ]) {
    const corrupted = structuredClone(status); change(corrupted);
    expect(() => evaluatePublicScenarios(data, base, corrupted)).toThrow();
  }
  expect(evaluatePublicScenarios(data, base)).toMatchObject({ mismatches: 65, passed: false });
});
