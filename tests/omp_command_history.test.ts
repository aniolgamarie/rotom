import { test, expect } from "bun:test";
import { isDeepStrictEqual } from "node:util";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { mkdtempSync, rmSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { gzipSync } from "node:zlib";
import { parseGenericCommands, matchesNativePattern } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";
import { loadGolden, evaluateGolden, evaluateCorpus, readCorpusFile, stripTrailingComment } from "../scripts/check-omp-command-history";

const cases = loadGolden(join(import.meta.dir, "fixtures/omp/command-history/cases.json"));
for (const item of cases.filter(item => item.category !== "known-semantic-gap")) {
  test(`${item.id} ${item.category}: independent argv and connector expectation`, () => {
    expect(parseGenericCommands(item.command)).toEqual(item.expected);
  });
}

test("known comment defects are reported as semantic failures, separately from a stable baseline", () => {
  const report = evaluateGolden(cases);
  const expected = cases.filter(c => c.category === "known-semantic-gap" &&
    !isDeepStrictEqual(parseGenericCommands(c.command), c.expected)).map(c => c.id);
  expect(report.knownSemanticFailures).toEqual(expected);
  expect(report.unexpectedFailures).toEqual([]);
  expect(report.baselinePassed).toBe(true);
  expect(report.semanticConformancePassed).toBe(expected.length === 0);
  expect(report.counts["coverage-gap"]).toBeGreaterThan(0);
});

test("all commands in read-then-dangerous compound inputs remain visible to native pattern matching", () => {
  for (const item of cases.filter(c => c.basis === "synthetic-policy-control" && c.command.includes(";"))) {
    const result = parseGenericCommands(item.command);
    expect(result.status).toBe("complete");
    if (result.status !== "complete") throw new Error("compound not parsed");
    expect(result.commands).toHaveLength(2);
    expect(result.commands.some(command => matchesNativePattern(command, "rm -rf *"))).toBe(true);
    expect(matchesNativePattern(result.commands[0], "rm -rf *")).toBe(false);
  }
  const result = parseGenericCommands("printf '%s' 'rm -rf /'");
  expect(result.status).toBe("complete");
  if (result.status === "complete") expect(matchesNativePattern(result.commands[0], "rm -rf *")).toBe(false);
});

test("a known comment error does not exempt a new parse regression", () => {
  const known = cases.find(c => c.id === "H077")!;
  const report = evaluateGolden([{ ...known, command: "echo changed # note" }]);
  expect(report.knownSemanticFailures).toEqual(["H077"]);
  expect(report.unexpectedFailures).toEqual(["H077"]);
  expect(report.baselinePassed).toBe(false);
  const resolved = evaluateGolden([{ ...known, command: "echo ok" }]);
  expect(resolved.resolvedSemanticGaps).toEqual(["H077"]);
  expect(resolved.semanticConformancePassed).toBe(true);
});

test("comment oracle preserves quoted, escaped and mid-word hashes", () => {
  expect(stripTrailingComment("echo ok # note")).toBe("echo ok ");
  expect(stripTrailingComment("echo '#literal' # note")).toBe("echo '#literal' ");
  expect(stripTrailingComment('echo "#literal" # note')).toBe('echo "#literal" ');
  expect(stripTrailingComment("echo \\#literal # note")).toBe("echo \\#literal ");
  expect(stripTrailingComment("echo foo#bar")).toBe("echo foo#bar");
});

function fixtureCorpus(commands: string[]) {
  const counters = (extracted: number) => ({ files: 1, events: extracted, extracted,
    unsupportedCommandCarrier: 0, malformed: 0, redactionSkipped: 0, dynamicCommandSkipped: 0, nonCommand: 0,
    jsScripts: 0, jsLiteralCommands: 0, jsUnresolvedCalls: 0, jsMalformedScripts: 0 });
  return { schemaVersion: 1, redactionVersion: 1, publication: "private-review-required",
    statistics: { pi: counters(commands.length), codex: counters(0), omp: counters(0) },
    records: commands.map(command => ({ id: createHash("sha256").update(command).digest("hex"),
      command, sources: ["pi"], occurrences: 1 })) };
}

test("history report separates refusal, partial semantic failures and acceptance without revealing commands", () => {
  const corpus = fixtureCorpus(["pwd", "ls *.jar", "echo ok # note"]);
  const report = evaluateCorpus(corpus);
  expect(report.uniqueCommands).toBe(3);
  expect(report.complete).toBe(2);
  expect(report.unsupported).toBe(1);
  expect(report.thrown).toBe(0);
  expect(report.commentOracleEligible).toBe(1);
  expect(report.commentOracleMismatches).toBe(1);
  expect(report.acceptanceRate).toBe(2 / 3);
  expect(JSON.stringify(report)).not.toContain("echo ok");
});

test("malformed or ambiguous corpus metadata fails instead of being silently discarded", () => {
  const corpus = fixtureCorpus(["pwd"]);
  expect(() => evaluateCorpus({ ...corpus, unknown: true })).toThrow();
  expect(() => evaluateCorpus({ ...corpus, records: [...corpus.records, ...corpus.records] })).toThrow();
  expect(() => evaluateCorpus({ ...corpus, records: [{ ...corpus.records[0], sources: ["unknown"] }] })).toThrow();
  expect(() => evaluateCorpus({ ...corpus, records: [{ ...corpus.records[0], occurrences: 2 }] })).toThrow();
  expect(() => evaluateCorpus({ ...corpus, statistics: { ...corpus.statistics, extra: {} } })).toThrow();
});

test("bounded generated literal inputs have exact independent token results; truncation fails closed", () => {
  for (let i = 0; i < 128; i++) {
    const token = `file_${i}_with_spaces`;
    expect(parseGenericCommands(`printf '%s' '${token};|&&' && pwd`)).toEqual({ status: "complete", commands: [
      { connector: "start", argv: ["printf", "%s", `${token};|&&`] }, { connector: "&&", argv: ["pwd"] },
    ] });
    expect(parseGenericCommands(`printf '%s' '${token}`)).toEqual({ status: "unsupported", reason: "unsupported-syntax" });
  }
});

test("scenario evaluation preserves weighted occurrences and validates all selection metadata", () => {
  const raw = fixtureCorpus(["ls first.txt", "ls second.txt", "ls *.jar"]);
  const stats = Object.fromEntries(Object.entries(raw.statistics).map(([source, counters]) => [source, { ...counters, secondPassSkipped: 0 }]));
  const records = [
    { ...raw.records[0], occurrences: 2, scenario: { id: "a".repeat(64), category: "simple", features: [], members: 2 } },
    { ...raw.records[2], scenario: { id: "b".repeat(64), category: "glob", features: ["glob"], members: 1 } },
  ];
  const input = { ...raw, schemaVersion: 2, redactionVersion: 2, statistics: stats, records,
    selection: { classificationVersion: 1, inputUniqueCommands: 3, scenarioCount: 2, removedDuplicateCommands: 1,
      preservedOccurrences: 3, secondPassChecked: 3, secondPassFailures: 0, categories: { simple: 1, glob: 1 } } };
  const result = evaluateCorpus(input);
  expect(result.uniqueCommands).toBe(2);
  expect(result.occurrences).toBe(3);
  expect(result.sampling).toBe("lexical-scenario-representatives");
  expect(result.complete).toBe(1);
  expect(result.unsupported).toBe(1);
  expect(() => evaluateCorpus({ ...input, selection: { ...input.selection, scenarioCount: 3 } })).toThrow();
  expect(() => evaluateCorpus({ ...input, selection: { ...input.selection, secondPassFailures: 1 } })).toThrow();
  expect(() => evaluateCorpus({ ...input, records: records.map(r => ({ ...r, scenario: { ...r.scenario, id: "a".repeat(64) } })) })).toThrow();
  expect(() => evaluateCorpus({ ...input, schemaVersion: "2" })).toThrow();
});

test("private corpus loading supports gzip and rejects corruption or oversized input", () => {
  const directory = mkdtempSync(join(tmpdir(), "omp-history-reader-"));
  try {
    const input = fixtureCorpus(["pwd"]);
    const plain = join(directory, "corpus.json");
    const compressed = join(directory, "corpus.json.gz");
    writeFileSync(plain, JSON.stringify(input), { mode: 0o600 });
    writeFileSync(compressed, gzipSync(JSON.stringify(input)), { mode: 0o600 });
    expect(evaluateCorpus(readCorpusFile(compressed))).toEqual(evaluateCorpus(readCorpusFile(plain)));
    writeFileSync(compressed, "invalid gzip");
    expect(() => readCorpusFile(compressed)).toThrow();
    truncateSync(plain, 64 * 1024 * 1024 + 1);
    expect(() => readCorpusFile(plain)).toThrow();
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
