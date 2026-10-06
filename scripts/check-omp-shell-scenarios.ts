import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { join } from "node:path";
import { readCorpusFile } from "./check-omp-command-history";
import { parseGenericCommands } from "../agents/omp/packages/omp-permission-control/standalone-shell-analysis";

function keys(value: any, expected: string[]) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join() !== expected.sort().join()) throw new Error("invalid public corpus");
}

export function evaluatePublicScenarios(data: any) {
  keys(data, ["schemaVersion", "publication", "oracleVersion", "records", "summary"]);
  keys(data.summary, ["inputScenarios", "publicCases", "mergedRebuiltCases", "representedScenarios", "categories", "expectedComplete", "expectedUnsupported"]);
  if (data.schemaVersion !== 1 || data.oracleVersion !== 1 || data.publication !== "synthetic-public" || !Array.isArray(data.records) || !data.records.length) throw new Error("invalid public corpus");
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
    try { if (!isDeepStrictEqual(parseGenericCommands(row.command), row.expected)) mismatches.push(row.id); }
    catch { thrown++; }
  }
  const s = data.summary;
  if (s.publicCases !== data.records.length || s.inputScenarios !== represented || s.representedScenarios !== represented ||
      s.mergedRebuiltCases !== represented-data.records.length || s.expectedComplete !== complete || s.expectedUnsupported !== unsupported || !isDeepStrictEqual(s.categories, categories)) throw new Error("invalid public summary");
  return { cases: data.records.length, representedScenarios: represented, complete, unsupported, mismatches: mismatches.length,
    firstMismatchIds: mismatches.slice(0, 10), thrown, passed: mismatches.length === 0 && thrown === 0,
    semantics: "declared-static-grammar-and-conservative-boundaries; not-full-shell-or-model-quality", shellCommandsExecuted: 0, modelRequests: 0 };
}

if (import.meta.main) {
  try {
    const report = evaluatePublicScenarios(readCorpusFile(join(import.meta.dir, "../tests/fixtures/omp/command-scenarios/corpus.json.gz")));
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = report.passed ? 0 : 1;
  } catch { console.error("public scenario check failed: invalid fixture"); process.exitCode = 2; }
}
