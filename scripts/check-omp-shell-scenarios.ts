import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { join } from "node:path";
import { readCorpusFile } from "./check-omp-command-history";
import { parseGenericCommands } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";

function keys(value: any, expected: string[]) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join() !== expected.sort().join()) throw new Error("invalid public corpus");
}

const CORPUS_SHA256 = "d6e5dc5d68c685d44949a0487f7ff71bd60b28daad228c20ec8070d39a710699";
const PARSE_OVERLAY_SHA256 = "81c8d0a99bcadc8ef8da7ff12a99da2eaa7c74308c022b9cc0c0d27f65a64d03";
const FIXTURES = join(import.meta.dir, "../tests/fixtures/omp/command-scenarios");

function canonical(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}

function digest(value: any): string { return createHash("sha256").update(canonical(value)).digest("hex"); }

function fixedParseOverlay(data: any, overlay: any): Map<string, any> {
  keys(overlay, ["schemaVersion", "oracleVersion", "purpose", "sourceCorpusSha256", "sourceCorpusCanonicalSha256", "sourceGateOverlaySha256", "sourceOracleSha256", "sourceRowDigestMethod", "counts", "entries"]);
  // 固定差量整体指纹阻止调用者改写oracle；原行指纹阻止换行或换预期后沿用ID。
  if (digest(overlay) !== PARSE_OVERLAY_SHA256 || overlay.sourceCorpusSha256 !== CORPUS_SHA256 ||
      digest(data) !== overlay.sourceCorpusCanonicalSha256 ||
      createHash("sha256").update(readFileSync(join(import.meta.dir, "omp-shell-review-oracle.py"))).digest("hex") !== overlay.sourceOracleSha256)
    throw new Error("invalid fixed parse overlay fingerprint");
  const gate = JSON.parse(readFileSync(join(FIXTURES, "grammar-upgrade-20261009.json"), "utf8"));
  if (digest(gate) !== overlay.sourceGateOverlaySha256 || overlay.entries.length !== 583) throw new Error("invalid fixed parse overlay source");
  const refs = new Map<string, any>(gate.entries.map((entry: any) => [entry.id, entry]));
  const entries = new Map<string, any>();
  for (const entry of overlay.entries) {
    keys(entry, ["id", "sourceRowSha256", "category", "reason", "fullParse"]);
    const ref = refs.get(entry.id);
    if (!ref || entries.has(entry.id) || entry.sourceRowSha256 !== ref.sourceRowSha256 || entry.category !== ref.category ||
        entry.fullParse?.status !== "complete") throw new Error("invalid fixed parse overlay entry");
    entries.set(entry.id, entry);
  }
  if (entries.size !== refs.size) throw new Error("missing fixed parse overlay entry");
  return entries;
}

function fixedStatusOverlay(data: any, overlay: any): Map<string, any> {
  keys(overlay, ["schemaVersion", "purpose", "sourceCorpusSha256", "sourceOracleSha256", "count", "entries"]);
  if (digest(overlay) !== "c170529b91aa45ee33c1b568dfe6e64c75d8c1a2546b4182de0d009fa1847858" ||
      overlay.sourceCorpusSha256 !== CORPUS_SHA256 || overlay.count !== 65 || overlay.entries.length !== 65 ||
      createHash("sha256").update(readFileSync(join(import.meta.dir, "omp-shell-status-oracle.py"))).digest("hex") !== overlay.sourceOracleSha256)
    throw new Error("invalid fixed status overlay fingerprint");
  const rows = new Map<string, any>(data.records.map((row: any) => [row.id, row]));
  const result = new Map<string, any>();
  for (const entry of overlay.entries) {
    keys(entry, ["id", "sourceRowSha256", "oldGate", "expectedGate", "fullParse"]);
    const row = rows.get(entry.id);
    if (!row || result.has(entry.id) || digest(row) !== entry.sourceRowSha256 || row.expectedGate !== "human" ||
        row.expected.status !== "unsupported" || entry.oldGate !== "human" || entry.expectedGate !== "review" || entry.fullParse?.status !== "complete")
      throw new Error("invalid fixed status overlay row");
    result.set(entry.id, entry);
  }
  return result;
}

export function evaluatePublicScenarios(data: any, overlay?: any, statusOverlay?: any) {
  keys(data, ["schemaVersion", "publication", "oracleVersion", "records", "summary"]);
  keys(data.summary, ["inputScenarios", "publicCases", "mergedRebuiltCases", "representedScenarios", "categories", "expectedComplete", "expectedUnsupported"]);
  if (data.schemaVersion !== 1 || data.oracleVersion !== 1 || data.publication !== "synthetic-public" || !Array.isArray(data.records) || !data.records.length) throw new Error("invalid public corpus");
  // 小fixture默认使用自身v1预期，只有显式提供已冻结差量才应用v2结构。
  const upgraded = overlay === undefined ? new Map<string, any>() : fixedParseOverlay(data, overlay);
  if (statusOverlay !== undefined) for (const [id, entry] of fixedStatusOverlay(data, statusOverlay)) {
    if (upgraded.has(id)) throw new Error("overlapping fixed overlays");
    upgraded.set(id, entry);
  }
  let complete = 0, unsupported = 0, represented = 0, thrown = 0;
  const mismatches: string[] = [];
  const ids = new Set<string>();
  const categories: Record<string, number> = {};
  for (const row of data.records) {
    keys(row, ["id", "command", "category", "features", "representedScenarios", "expected", "expectedGate"]);
    if (typeof row.command !== "string" || ids.has(row.id) || row.id !== createHash("sha256").update(row.command).digest("hex") ||
      !Number.isSafeInteger(row.representedScenarios) || row.representedScenarios < 1 || !["model", "human"].includes(row.expectedGate) ||
      !["invalid-boundary", "control-flow", "dynamic", "heredoc", "redirection", "multiline", "glob", "comment", "compound", "simple"].includes(row.category) || !Array.isArray(row.features) || row.features.some((f: unknown) => typeof f !== "string")) throw new Error("invalid public row");
    if (!["complete", "unsupported"].includes(row.expected?.status)) throw new Error("invalid oracle");
    row.expected.status === "complete" ? complete++ : unsupported++;
    represented += row.representedScenarios;
    categories[row.category] = (categories[row.category] ?? 0)+1;
    ids.add(row.id);
    const delta = upgraded.get(row.id);
    if (delta && (digest(row) !== delta.sourceRowSha256 || row.expected.status !== "unsupported")) throw new Error("invalid original overlay row");
    try { if (!isDeepStrictEqual(parseGenericCommands(row.command), delta ? delta.fullParse : row.expected)) mismatches.push(row.id); }
    catch { thrown++; }
  }
  const s = data.summary;
  if (s.publicCases !== data.records.length || s.inputScenarios !== represented || s.representedScenarios !== represented ||
      s.mergedRebuiltCases !== represented-data.records.length || s.expectedComplete !== complete || s.expectedUnsupported !== unsupported || !isDeepStrictEqual(s.categories, categories)) throw new Error("invalid public summary");
  // complete/unsupported保留兼容且指冻结v1预期；effective指应用差量后的解析预期，不是人工审批gate数量。
  return { cases: data.records.length, representedScenarios: represented, complete, unsupported,
    frozenComplete: complete, frozenUnsupported: unsupported,
    effectiveComplete: complete + upgraded.size, effectiveUnsupported: unsupported - upgraded.size,
    upgradedParses: upgraded.size, mismatches: mismatches.length,
    firstMismatchIds: mismatches.slice(0, 10), thrown, passed: mismatches.length === 0 && thrown === 0,
    semantics: "declared-static-grammar-and-conservative-boundaries; not-full-shell-or-model-quality", shellCommandsExecuted: 0, modelRequests: 0 };
}

if (import.meta.main) {
  try {
    const path = join(FIXTURES, "corpus.json.gz");
    if (createHash("sha256").update(readFileSync(path)).digest("hex") !== CORPUS_SHA256) throw new Error("invalid frozen corpus fingerprint");
    const report = evaluatePublicScenarios(readCorpusFile(path), JSON.parse(readFileSync(join(FIXTURES, "grammar-parse-upgrade-20261009.json"), "utf8")),
      JSON.parse(readFileSync(join(FIXTURES, "grammar-status-upgrade-20261010.json"), "utf8")));
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = report.passed ? 0 : 1;
  } catch { console.error("public scenario check failed: invalid fixture"); process.exitCode = 2; }
}
