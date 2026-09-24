import { createHash } from "node:crypto";
import { ContractError, digest, object } from "./primitives.ts";
import { parseCsv, verifyScenarioMapping, type TestExecution } from "./test-plan.ts";

export interface AcceptanceBundle {
  revision: "TK-R2";
  files: Record<string, string>;
  hashes: Record<string, string>;
  legacy: { files: Record<string, string>; hashes: Record<string, string>; matrices: Array<{id: string; layers: string[]; cases: Array<{id: string; input: string; expected: string}>}> };
}
export interface AcceptancePlan {
  revision: "TK-R2"; digest: string; scenarios: Record<string, string>[];
  cases: Array<{id: string; variants: string[]; observer: string}>;
  legacyIds: string[];
}
export const textHash = (value: string) => createHash("sha256").update(value).digest("hex");
function fail(code: string, detail = code): never { throw new ContractError(code, detail); }
function unique(values: string[], code: string) {
  if (!values.length || values.some(value => !value) || new Set(values).size !== values.length) fail(code);
}
export function validateAcceptanceBundle(bundle: AcceptanceBundle): AcceptancePlan {
  object(bundle, ["revision", "files", "hashes", "legacy"]);
  if (bundle.revision !== "TK-R2") fail("UNKNOWN_PLAN_REVISION");
  for (const section of [bundle, bundle.legacy]) {
    object(section.files); object(section.hashes);
    if (digest(Object.keys(section.files).sort()) !== digest(Object.keys(section.hashes).sort())) fail("PLAN_FILE_INVENTORY_MISMATCH");
    for (const [file, value] of Object.entries(section.files)) {
      if (file.startsWith("/") || file.split("/").includes("..") || typeof value !== "string" || textHash(value) !== section.hashes[file]) fail("PLAN_SOURCE_HASH_MISMATCH", file);
    }
  }
  const required = (file: string) => { const text = bundle.files[file]; if (typeof text !== "string") return fail("MISSING_PLAN_FILE", file); return text; };
  const revision = JSON.parse(required("scope-revision.json"));
  const scenarios = parseCsv(required("scenario-test-matrix.csv"));
  const caseRows = parseCsv(required("acceptance-cases.csv"));
  unique(scenarios.map(row => row.scenario_id), "DUPLICATE_SCENARIO_ID");
  unique(caseRows.map(row => row.case_id), "DUPLICATE_ACCEPTANCE_ID");
  const cases = caseRows.map(row => {
    if (!/^AC\d{2}$/.test(row.case_id) || !row.required_outcome || !row.independent_observer) fail("INVALID_ACCEPTANCE_CASE");
    const variants = row.variants.split(";"); unique(variants, "DUPLICATE_ACCEPTANCE_VARIANT");
    if (variants.some(variant => !/^[a-zA-Z0-9.-]+$/.test(variant))) fail("INVALID_ACCEPTANCE_VARIANT");
    return { id: row.case_id, variants, observer: row.independent_observer };
  });
  if (revision.revision !== bundle.revision || revision.scenarioCount !== scenarios.length || revision.variantCount !== cases.reduce((n, c) => n + c.variants.length, 0)
    || digest([...revision.acceptanceCases].sort()) !== digest(cases.map(c => c.id).sort())) fail("PLAN_REVISION_INVENTORY_MISMATCH");
  const specs = Object.fromEntries(Object.entries(bundle.files).filter(([file]) => /^specs\/[^/]+\/spec.md$/.test(file)));
  if (Object.keys(specs).length !== revision.specCount) fail("PLAN_SPEC_INVENTORY_MISMATCH");
  verifyScenarioMapping(specs, scenarios);
  const checkReferences = (value: string) => {
    if (!value || value.split(";").some(id => !cases.some(c => c.id === id))) fail("UNKNOWN_ACCEPTANCE_REFERENCE");
  };
  for (const row of scenarios) checkReferences(row.acceptance_cases);
  const legacyScenarios = parseCsv(bundle.legacy.files["scenario-test-matrix.csv"]);
  const legacyFaults = parseCsv(bundle.legacy.files["fault-traceability.csv"]);
  const original = [...legacyScenarios, ...legacyFaults];
  const originalIds = original.map(row => row.scenario_id ?? row.id); unique(originalIds, "DUPLICATE_LEGACY_ID");
  const mappings = parseCsv(required("legacy-obligation-map.csv"));
  unique(mappings.map(row => row.legacy_id), "DUPLICATE_LEGACY_MAPPING");
  if (digest(mappings.map(row => row.legacy_id).sort()) !== digest(originalIds.sort())) fail("LEGACY_MAPPING_MISSING");
  for (const row of mappings) {
    const old = original.find(item => (item.scenario_id ?? item.id) === row.legacy_id)!;
    if (row.original_required_layers !== old.required_layers || !row.reason || row.runtime_credit !== "not-imported"
      || !["retained", "refined", "split", "deferred"].includes(row.disposition)) fail("INVALID_LEGACY_DISPOSITION");
    checkReferences(row.current_acceptance);
  }
  const matrix = parseCsv(required("legacy-matrix-map.csv"));
  unique(matrix.map(row => row.legacy_key), "DUPLICATE_LEGACY_MATRIX");
  const expected = new Map<string, { id: string; input: string; expected: string }>(bundle.legacy.matrices.flatMap(m => m.cases.flatMap(c => m.layers.map(layer => [`${m.id}:${c.id}:${layer}`, c] as const))));
  if (digest(matrix.map(row => row.legacy_key).sort()) !== digest([...expected.keys()].sort())) fail("LEGACY_MATRIX_MAPPING_MISSING");
  for (const row of matrix) {
    const old = expected.get(row.legacy_key)!;
    if (row.original_input !== old.input || row.original_expected !== old.expected || !row.reason || row.runtime_credit !== "not-imported") fail("LEGACY_MATRIX_SEMANTICS_CHANGED");
    checkReferences(row.current_acceptance);
  }
  return { revision: bundle.revision, digest: digest(bundle), scenarios, cases, legacyIds: originalIds };
}

export interface AcceptanceWitness { artifact: string; observer: string; predicate: string; level: string }
export interface AcceptanceEvidence extends AcceptanceWitness {
  caseId: string; variant: string; file: string; name: string; status: "passed" | "failed" | "skipped";
  assertions: number; sourceDigest: string; planDigest: string; artifactDigest: string;
}
export function acceptanceCoverage(plan: AcceptancePlan, evidence: AcceptanceEvidence[], sourceDigest: string) {
  const keys = plan.cases.flatMap(c => c.variants.map(v => `${c.id}.${v}`));
  const missing: string[] = [], failed: string[] = [], credited: string[] = [];
  for (const e of evidence) {
    if (!keys.includes(`${e.caseId}.${e.variant}`)) fail("UNKNOWN_ACCEPTANCE_VARIANT");
    if (!Number.isSafeInteger(e.assertions) || e.assertions < 0 || !["passed", "failed", "skipped"].includes(e.status)
      || !["U", "S", "A", "P", "E", "V"].includes(e.level)) fail("INVALID_ACCEPTANCE_EVIDENCE");
    const levels: string[] = [...(/^\[([^\]]+)\]/.exec(e.name)?.[1].match(/\b[USAPEV]\b/g) ?? [])];
    if (!levels.includes(e.level)) fail("ACCEPTANCE_LAYER_MISMATCH");
  }
  for (const key of keys) {
    const rows = evidence.filter(e => `${e.caseId}.${e.variant}` === key);
    const bad = rows.some(e => e.status !== "passed");
    if (rows.some(e => e.status === "failed")) failed.push(key);
    const valid = rows.some(e => e.assertions > 0 && e.sourceDigest === sourceDigest && e.planDigest === plan.digest
      && e.file && e.name && e.artifact && e.artifactDigest && e.observer && e.predicate);
    if (!bad && valid) credited.push(key); else missing.push(key);
  }
  const missingScenarios = plan.scenarios.filter(row => row.acceptance_cases.split(";").some(id => missing.some(key => key.startsWith(id + ".")))).map(row => row.scenario_id);
  return { revision: plan.revision, planDigest: plan.digest, planned: keys.length, credited, missing, failed, missingScenarios, scenarioCoverageBasis:"derived-from-AC-mapping", semanticReview:"not-automatically-verified", ready: !!keys.length && !missing.length && !failed.length };
}
export type AcceptanceExecution = TestExecution & { acceptanceWitnesses?: Record<string, AcceptanceWitness> };
