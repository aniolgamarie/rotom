import { createHash } from "node:crypto";
import { ContractError } from "./primitives.ts";

export function parseCsv(input: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  const text = input.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (c === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((c === "\n" || c === "\r") && !quoted) {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); if (row.some(Boolean)) rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (quoted) throw new ContractError("INVALID_CSV");
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const header = rows.shift();
  if (!header?.length || new Set(header).size !== header.length) throw new ContractError("INVALID_CSV_HEADER");
  return rows.map((cells) => {
    if (cells.length !== header.length) throw new ContractError("INVALID_CSV_ROW");
    return Object.fromEntries(header.map((key, i) => [key, cells[i]]));
  });
}

export interface TestObligation {
  id: string;
  source: "scenario" | "fault";
  levels: string[];
  phase: string;
  planned: boolean;
}

export function planObligations(scenarios: Record<string, string>[], faults: Record<string, string>[]): TestObligation[] {
  if (!scenarios.length || !faults.length) throw new ContractError("EMPTY_TEST_PLAN");
  const result: TestObligation[] = [];
  const ids = new Set<string>();
  for (const [source, rows] of [["scenario", scenarios], ["fault", faults]] as const) {
    for (const row of rows) {
      const id = row.scenario_id ?? row.id;
      if (!id || ids.has(id)) throw new ContractError("DUPLICATE_TEST_ID");
      ids.add(id);
      if (!row.required_layers || !row.test_families || !row.expected) throw new ContractError("INCOMPLETE_TEST_OBLIGATION", id);
      const levels = row.required_layers.split(";");
      if (levels.some((level) => !["U", "S", "A", "P", "E", "L", "V"].includes(level))) {
        throw new ContractError("INVALID_TEST_LEVEL", id);
      }
      result.push({ id, source, levels, phase: row.phase_gates ?? row.release_gate, planned: true });
    }
  }
  return result;
}

export function verifyScenarioMapping(specs: Record<string, string>, rows: Record<string, string>[]): void {
  const actual = new Map<string, string>();
  for (const [path, content] of Object.entries(specs)) {
    for (const block of content.split(/^### Requirement: /m).slice(1)) {
      const requirement = block.split("\n")[0];
      const cases = block.split(/^#### Scenario: /m).slice(1);
      if (!cases.length) throw new ContractError("REQUIREMENT_WITHOUT_SCENARIO");
      for (const scenario of cases) {
        const name = scenario.split("\n")[0];
        const when = /^- \*\*WHEN\*\* (.+)$/m.exec(scenario)?.[1];
        const then = /^- \*\*THEN\*\* (.+)$/m.exec(scenario)?.[1];
        if (!when || !then) throw new ContractError("INVALID_SCENARIO");
        const key = JSON.stringify([path, requirement, name]);
        if (actual.has(key)) throw new ContractError("DUPLICATE_SCENARIO");
        actual.set(key, createHash("sha256").update([requirement, name, when, then].join("\n")).digest("hex"));
      }
    }
  }
  if (!actual.size || actual.size !== rows.length) throw new ContractError("TEST_MAPPING_DRIFT");
  for (const row of rows) {
    const key = JSON.stringify([row.spec_path, row.requirement, row.scenario]);
    if (actual.get(key) !== row.spec_digest) throw new ContractError("TEST_MAPPING_DRIFT", row.scenario_id);
    actual.delete(key);
  }
  if (actual.size) throw new ContractError("TEST_MAPPING_DRIFT");
}

export interface TestEvidence {
  id: string;
  level: string;
  status: "passed" | "failed" | "skipped";
  assertions: number;
  file: string;
  name: string;
  artifact: string;
  lockDigest: string;
}

/** Release reporting consumes evidence; it never infers passing from a registered name. */
export function coverageReport(obligations: TestObligation[], evidence: TestEvidence[], lockDigest: string) {
  const known = new Map(obligations.map((o) => [o.id, o]));
  for (const item of evidence) {
    if (!known.has(item.id)) throw new ContractError("UNKNOWN_TEST_ID", item.id);
    if (!known.get(item.id)!.levels.includes(item.level)) throw new ContractError("UNDECLARED_TEST_LEVEL");
    if (!Number.isSafeInteger(item.assertions) || item.assertions < 0
      || !["passed", "failed", "skipped"].includes(item.status)) throw new ContractError("INVALID_TEST_EVIDENCE");
  }
  const missing: string[] = [], failed: string[] = [];
  for (const item of obligations) for (const level of item.levels) {
    const matches = evidence.filter((e) => e.id === item.id && e.level === level);
    // Preserve failures from the same evaluation; rerunning until green is not a pass.
    if (matches.some((e) => e.status === "failed")) failed.push(`${item.id}:${level}`);
    if (matches.some(e => e.status === "skipped") || !matches.some((e) => e.status === "passed" && e.assertions > 0 && e.file && e.name && e.artifact && e.lockDigest === lockDigest)) {
      missing.push(`${item.id}:${level}`);
    }
  }
  return { planned: obligations.length, evidenceRecords: evidence.length, missing, failed,
    ready: obligations.length > 0 && missing.length === 0 && failed.length === 0,
    codeCoverage: "unavailable" as const };
}

export interface TestIdentity { file: string; name: string }
export interface TestExecution extends TestIdentity {
  status: "passed" | "failed" | "skipped"; assertions: number; attributed?: Record<string, number>;
  matrixAssertions?: Record<string, number>;
}
export function testIds(name: string): string[] {
  return [...new Set(name.match(/\b(?:T\d{2}|TK\d{2}|(?:CFG|EXE|EVD|REC|SCH|WFL|RTB|VAL)-\d{3})\b/g) ?? [])];
}
/** A discovered name is not an executed test; aggregate assertions do not certify several IDs. */
export function validateDiscovery(discovered: TestIdentity[], executions: TestExecution[], obligations: TestObligation[]) {
  const known = new Set(obligations.map(o => o.id));
  const identity = (item: TestIdentity) => JSON.stringify([item.file, item.name]);
  const declared = new Set<string>();
  if (!discovered.length || !executions.length) throw new ContractError("ZERO_DISCOVERED_OR_EXECUTED_TESTS");
  for (const item of discovered) {
    if (!item.file || !item.name || declared.has(identity(item))) throw new ContractError("DUPLICATE_OR_INVALID_TEST_IDENTITY");
    declared.add(identity(item));
    for (const id of testIds(item.name)) if (!known.has(id)) throw new ContractError("UNKNOWN_TEST_ID", id);
  }
  const actual = new Set<string>();
  for (const item of executions) {
    if (!declared.has(identity(item)) || actual.has(identity(item))) throw new ContractError("UNDISCOVERED_OR_DUPLICATE_EXECUTION");
    actual.add(identity(item));
    const ids = testIds(item.name);
    for (const [id, count] of Object.entries(item.attributed ?? {})) {
      if (!ids.includes(id) || !Number.isSafeInteger(count) || count < 0) throw new ContractError("INVALID_ASSERTION_ATTRIBUTION", id);
    }
    if (Object.values(item.attributed ?? {}).reduce((a, b) => a + b, 0) > item.assertions) throw new ContractError("INVALID_ASSERTION_ATTRIBUTION");
    if (Object.values(item.matrixAssertions ?? {}).some(count => !Number.isSafeInteger(count) || count < 0)
      || Object.values(item.matrixAssertions ?? {}).reduce((a, b) => a + b, 0) > item.assertions) throw new ContractError("INVALID_MATRIX_ATTRIBUTION");
  }
  return { notExecuted: discovered.filter(item => !actual.has(identity(item))),
    unattributed: executions.flatMap(item => testIds(item.name).filter(id => testIds(item.name).length > 1 && !((item.attributed?.[id] ?? 0) > 0)).map(id => ({ ...item, id }))) };
}

export interface ExpandedMatrix { id: string; layers: string[]; cases: Array<{ id: string }> }
export interface MatrixEvidence extends Omit<TestEvidence, "id"> { matrix: string; variant: string }
export function matrixCoverage(plan: ExpandedMatrix[], evidence: MatrixEvidence[], lockDigest: string) {
  const obligations = new Set<string>();
  for (const matrix of plan) for (const variant of matrix.cases) for (const layer of matrix.layers) {
    const key = `${matrix.id}:${variant.id}:${layer}`;
    if (obligations.has(key)) throw new ContractError("DUPLICATE_MATRIX_OBLIGATION");
    obligations.add(key);
  }
  for (const item of evidence) {
    if (!obligations.has(`${item.matrix}:${item.variant}:${item.level}`)) throw new ContractError("UNKNOWN_MATRIX_OBLIGATION");
    if (!Number.isSafeInteger(item.assertions) || item.assertions < 0) throw new ContractError("INVALID_MATRIX_ATTRIBUTION");
  }
  const credited: string[] = [], missing: string[] = [], failed: string[] = [];
  for (const key of obligations) {
    const records = evidence.filter(item => `${item.matrix}:${item.variant}:${item.level}` === key);
    if (records.some(item => item.status === "failed")) failed.push(key);
    const passed = records.some(item => item.status === "passed" && item.assertions > 0 && item.file && item.name && item.artifact && item.lockDigest === lockDigest);
    if (!passed || records.some(item => item.status === "skipped" || item.status === "failed")) missing.push(key);
    else credited.push(key);
  }
  return { planned: obligations.size, credited, missing, failed, ready: obligations.size > 0 && missing.length === 0 && failed.length === 0 };
}
export function attributedAssertions(execution: TestExecution, id: string): number {
  const ids = testIds(execution.name);
  if (!ids.includes(id)) return 0;
  return ids.length === 1 ? execution.assertions : execution.attributed?.[id] ?? 0;
}
