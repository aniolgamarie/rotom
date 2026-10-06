import { closeSync, fstatSync, openSync, readFileSync, writeFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { join } from "node:path";
import { gunzipSync } from "node:zlib";
import { parseGenericCommands, type GenericShellParse } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";

const SOURCES = ["pi", "codex", "omp"] as const;
type Source = typeof SOURCES[number];
export interface GoldenCase {
  id: string;
  command: string;
  basis: string;
  category: "supported" | "coverage-gap" | "conservative-boundary" | "known-semantic-gap";
  expected: GenericShellParse;
}
interface CorpusRecord { id: string; command: string; sources: Source[]; occurrences: number;
  scenario?: { id: string; category: string; features: string[]; members: number } }
const SCENE_CATEGORIES = ["invalid-boundary", "control-flow", "dynamic", "heredoc", "redirection", "multiline", "glob", "comment", "compound", "simple"];
const SCENE_FEATURES = [...SCENE_CATEGORIES.filter(c => c !== "simple"), "quote:single", "quote:double", "concatenation", "escape", "assignment", "write-command", "privilege-command", "embedded-code", "nested-write"];

// 已知错误只允许当前明确观察到的结果；不能借“已知错误”豁免新的行为偏离。
const KNOWN_COMMENT_BASELINES: Record<string, GenericShellParse> = {
  H077: { status: "complete", commands: [{ connector: "start", argv: ["echo", "ok", "#", "note"] }] },
  H078: { status: "unsupported", reason: "unsupported-syntax" },
  H079: { status: "complete", commands: [
    { connector: "start", argv: ["printf", "%s", "value", "#"] },
    { connector: ";", argv: ["rm", "-rf", "/"] },
  ] },
};

function exactKeys(value: unknown, keys: string[]): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).sort().join(",") !== [...keys].sort().join(",")) throw new Error("invalid shape");
}

export function loadGolden(path: string): GoldenCase[] {
  const input = JSON.parse(readFileSync(path, "utf8"));
  exactKeys(input, ["schemaVersion", "cases"]);
  if (input.schemaVersion !== 1 || !Array.isArray(input.cases)) throw new Error("invalid fixture");
  const ids = new Set<string>();
  for (const item of input.cases) {
    exactKeys(item, ["id", "command", "basis", "category", "expected"]);
    if (typeof item.id !== "string" || !/^H\d{3}$/u.test(item.id) || ids.has(item.id) ||
        typeof item.command !== "string" || typeof item.basis !== "string" ||
        !["supported", "coverage-gap", "conservative-boundary", "known-semantic-gap"].includes(String(item.category)))
      throw new Error("invalid fixture case");
    ids.add(item.id);
    const expected = item.expected as GenericShellParse;
    if (expected.status === "unsupported") {
      exactKeys(expected, ["status", "reason"]);
      if (expected.reason !== "unsupported-syntax") throw new Error("invalid expected result");
    } else if (expected.status === "complete") {
      exactKeys(expected, ["status", "commands"]);
      if (!Array.isArray(expected.commands) || !expected.commands.length) throw new Error("invalid commands");
      for (const command of expected.commands) {
        exactKeys(command, ["connector", "argv"]);
        if (!["start", "&&", "||", ";", "|"].includes(String(command.connector)) ||
            !Array.isArray(command.argv) || !command.argv.length || command.argv.some(a => typeof a !== "string"))
          throw new Error("invalid command");
      }
    } else throw new Error("invalid expected status");
  }
  return input.cases as unknown as GoldenCase[];
}

export function evaluateGolden(cases: GoldenCase[]) {
  const counts = { supported: 0, "coverage-gap": 0, "conservative-boundary": 0, "known-semantic-gap": 0 };
  const knownSemanticFailures: string[] = [];
  const unexpectedFailures: string[] = [];
  const resolvedSemanticGaps: string[] = [];
  let semanticMatches = 0;
  for (const item of cases) {
    counts[item.category]++;
    const actual = parseGenericCommands(item.command);
    const matches = isDeepStrictEqual(actual, item.expected);
    if (matches) {
      semanticMatches++;
      if (item.category === "known-semantic-gap") resolvedSemanticGaps.push(item.id);
    } else if (item.category === "known-semantic-gap") {
      knownSemanticFailures.push(item.id);
      if (!isDeepStrictEqual(actual, KNOWN_COMMENT_BASELINES[item.id])) unexpectedFailures.push(item.id);
    }
    else unexpectedFailures.push(item.id);
  }
  return { cases: cases.length, counts, semanticMatches, knownSemanticFailures, unexpectedFailures,
    resolvedSemanticGaps, baselinePassed: unexpectedFailures.length === 0,
    semanticConformancePassed: semanticMatches === cases.length };
}

/** 只用于当前字面量子集的独立注释 oracle；不解析或执行脚本。 */
export function stripTrailingComment(input: string): string {
  let quote: "single" | "double" | undefined;
  let wordStart = true;
  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (quote === "single") { if (ch === "'") quote = undefined; continue; }
    if (ch === "\\") { i++; wordStart = false; continue; }
    if (quote === "double") { if (ch === '"') quote = undefined; continue; }
    if (ch === "'" || ch === '"') { quote = ch === "'" ? "single" : "double"; wordStart = false; }
    else if (ch === "#" && wordStart) return input.slice(0, i);
    else wordStart = /[\s;&|]/u.test(ch);
  }
  return input;
}

function appearances(command: string): string[] {
  // 词法外观计数不冒充 AST 分类：引号中的字符也可能计入。
  const tags: string[] = [];
  if (/[\r\n]/u.test(command)) tags.push("multiline");
  if (/[*?\[]/u.test(command)) tags.push("glob-like");
  if (/[<>]/u.test(command)) tags.push("redirection-like");
  if (/\$|`/u.test(command)) tags.push("expansion-like");
  if (/[;&|]/u.test(command)) tags.push("connector-like");
  return tags;
}

export function evaluateCorpus(input: unknown) {
  if (!input || typeof input !== "object") throw new Error("invalid corpus");
  const version = (input as Record<string, unknown>).schemaVersion;
  exactKeys(input, ["schemaVersion", "publication", "records", "statistics", "redactionVersion", ...(version === 2 ? ["selection"] : [])]);
  if (![1, 2].includes(input.schemaVersion as number) || ![1, 2].includes(input.redactionVersion as number) ||
      (version === 2 && input.redactionVersion !== 2) || input.publication !== "private-review-required" ||
      !Array.isArray(input.records)) throw new Error("invalid corpus");
  exactKeys(input.statistics, [...SOURCES]);
  const counterKeys = ["files", "events", "extracted", "unsupportedCommandCarrier", "malformed", "redactionSkipped",
    "dynamicCommandSkipped", "nonCommand", "jsScripts", "jsLiteralCommands", "jsUnresolvedCalls", "jsMalformedScripts",
    ...(input.redactionVersion === 2 ? ["secondPassSkipped"] : [])];
  let extracted = 0;
  for (const source of SOURCES) {
    const counters = input.statistics[source];
    exactKeys(counters, counterKeys);
    if (Object.values(counters).some(v => !Number.isSafeInteger(v) || Number(v) < 0) ||
        Number(counters.dynamicCommandSkipped) > Number(counters.redactionSkipped)) throw new Error("invalid counters");
    extracted += Number(counters.extracted);
  }
  const bySource = Object.fromEntries(SOURCES.map(source => [source, { unique: 0, complete: 0, unsupported: 0 }])) as
    Record<Source, { unique: number; complete: number; unsupported: number }>;
  const featureAppearances: Record<string, { complete: number; unsupported: number }> = {};
  const ids = new Set<string>();
  const commands = new Set<string>();
  const scenarioIds = new Set<string>();
  const categories: Record<string, number> = {};
  let members = 0;
  let complete = 0;
  let unsupported = 0;
  let occurrences = 0;
  let thrown = 0;
  let commentOracleEligible = 0;
  let commentOracleMismatches = 0;
  for (const raw of input.records) {
    exactKeys(raw, ["id", "command", "sources", "occurrences", ...(version === 2 ? ["scenario"] : [])]);
    const record = raw as unknown as CorpusRecord;
    if (typeof record.id !== "string" || !/^[a-f0-9]{64}$/u.test(record.id) || ids.has(record.id) ||
        typeof record.command !== "string" || commands.has(record.command) ||
        !Array.isArray(record.sources) || !record.sources.length || new Set(record.sources).size !== record.sources.length ||
        record.sources.some(s => !SOURCES.includes(s)) || !Number.isSafeInteger(record.occurrences) || record.occurrences < 1)
      throw new Error("invalid corpus record");
    if (version === 2) {
      exactKeys(record.scenario, ["id", "category", "features", "members"]);
      const scene = record.scenario!;
      if (!/^[a-f0-9]{64}$/u.test(scene.id) || scenarioIds.has(scene.id) || !SCENE_CATEGORIES.includes(scene.category) ||
          !Array.isArray(scene.features) || scene.features.some(f => !SCENE_FEATURES.includes(f)) ||
          new Set(scene.features).size !== scene.features.length || !Number.isSafeInteger(scene.members) || scene.members < 1 ||
          scene.members > record.occurrences) throw new Error("invalid scenario");
      scenarioIds.add(scene.id);
      categories[scene.category] = (categories[scene.category] ?? 0) + 1;
      members += scene.members;
    }
    ids.add(record.id);
    commands.add(record.command);
    occurrences += record.occurrences;
    let result: GenericShellParse;
    try { result = parseGenericCommands(record.command); }
    catch { thrown++; continue; }
    result.status === "complete" ? complete++ : unsupported++;
    for (const source of record.sources) { bySource[source].unique++; bySource[source][result.status]++; }
    for (const tag of appearances(record.command)) {
      featureAppearances[tag] ??= { complete: 0, unsupported: 0 };
      featureAppearances[tag][result.status]++;
    }
    const stripped = stripTrailingComment(record.command);
    if (stripped !== record.command && result.status === "complete") {
      const reference = parseGenericCommands(stripped);
      if (reference.status === "complete") {
        commentOracleEligible++;
        if (!isDeepStrictEqual(reference, result)) commentOracleMismatches++;
      }
    }
  }
  if (extracted !== occurrences) throw new Error("inconsistent occurrence counts");
  if (version === 2) {
    exactKeys(input.selection, ["classificationVersion", "inputUniqueCommands", "scenarioCount", "removedDuplicateCommands",
      "preservedOccurrences", "secondPassChecked", "secondPassFailures", "categories"]);
    const selection = input.selection;
    if (selection.classificationVersion !== 1 || selection.inputUniqueCommands !== members || selection.scenarioCount !== input.records.length ||
        selection.removedDuplicateCommands !== members-input.records.length || selection.preservedOccurrences !== occurrences ||
        selection.secondPassChecked !== members || selection.secondPassFailures !== 0 || !isDeepStrictEqual(selection.categories, categories))
      throw new Error("inconsistent selection metadata");
  }
  return { uniqueCommands: input.records.length, occurrences, complete, unsupported, thrown,
    acceptanceRate: input.records.length ? complete / input.records.length : null,
    bySource, featureAppearances, commentOracleEligible, commentOracleMismatches,
    sampling: version === 2 ? "lexical-scenario-representatives" : "unique-command-text",
    selection: version === 2 ? input.selection : null,
    semantics: "acceptance-is-not-accuracy-or-approval; private-redaction-bias; partial-comment-oracle" };
}

export function readCorpusFile(path: string): unknown {
  const descriptor = openSync(path, "r");
  try {
    const info = fstatSync(descriptor);
    if (!info.isFile() || info.size > 64 * 1024 * 1024) throw new Error("invalid corpus size");
    const bytes = readFileSync(descriptor);
    return JSON.parse((path.endsWith(".gz") ? gunzipSync(bytes, { maxOutputLength: 64 * 1024 * 1024 }) : bytes).toString("utf8"));
  } finally { closeSync(descriptor); }
}

function main() {
  const argv = process.argv.slice(2);
  let corpusPath: string | undefined;
  let output: string | undefined;
  for (let i = 0; i < argv.length; i += 2) {
    if (i + 1 >= argv.length) throw new Error("missing argument");
    if (argv[i] === "--corpus" && !corpusPath) corpusPath = argv[i + 1];
    else if (argv[i] === "--output" && !output) output = argv[i + 1];
    else throw new Error("unknown argument");
  }
  const golden = evaluateGolden(loadGolden(join(import.meta.dir, "../tests/fixtures/omp/command-history/cases.json")));
  const corpus = corpusPath ? evaluateCorpus(readCorpusFile(corpusPath)) : null;
  const report = { schemaVersion: 1, parser: "standalone-shell-analysis", modelRequests: 0,
    shellCommandsExecuted: 0, golden, corpus };
  if (output) writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = golden.baselinePassed && (!corpus || corpus.thrown === 0) ? 0 : 1;
}

if (import.meta.main) {
  try { main(); }
  catch { console.error("command corpus check failed: invalid input or filesystem operation"); process.exitCode = 2; }
}
