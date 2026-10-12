import { strictJson } from "@agentcfg/pi-runtime/strict-json";
import { supervisedCommand } from "./supervisor.ts";
import { realpathSync } from "node:fs";
import { digest, ContractError, finiteInteger } from "../contracts/primitives.ts";
import type { VerificationBinding } from "../config.ts";
import { scrub } from "../reliability/classifier.ts";
import type { EvidenceOrigin } from "../evidence/records.ts";

export interface TestCounts { tests: number; passed: number; failed: number; skipped: number }
export interface VerificationResult {
  checkId: string; jobId: string; snapshot: string; bindingDigest: string; environmentDigest: string; contractDigest: string; specVersion: number | null; policyDigest: string | null;
  inputSnapshotDigest: string | null; snapshotComparison: "current" | "stale" | null; snapshotComparisonReason?: string;
  status: "passed" | "failed" | "unknown"; exitCode: number | null; reason: string;
  counts: TestCounts | null; stdout: string; stderr: string; truncated: boolean; terminationConfirmed: boolean;
  terminationCoverage: "agentcfg-supervisor";
  notSent: boolean;
  supervisor: Awaited<ReturnType<typeof supervisedCommand>>["supervisor"];
  failureCategory: "implementation" | "environment" | "unknown" | null;
  evidenceOrigin?: EvidenceOrigin | null;
  invocationWindow?: { startedAt: number; endedAt: number };
  executionFacts?: VerificationFacts;
  acceptanceBinding?: Pick<VerificationBinding,"kind"|"parser"|"minimumTests"|"requiredTestIds">;
}

export function verificationEnvironment(binding: VerificationBinding): NodeJS.ProcessEnv {
  return { PATH: process.env.PATH, LANG: "C.UTF-8", ...binding.environment };
}
export function verificationEnvironmentDigest(environment: NodeJS.ProcessEnv, supervisor: { executable: string; hash: string; engineHash: string }): string {
  const effective = Object.fromEntries(Object.entries(environment).filter(([, value]) => value !== undefined));
  return digest({ environment: { ...effective, NODE_NO_WARNINGS: "1" },
    supervisor: { executable: supervisor.executable, hash: supervisor.hash, engineHash: supervisor.engineHash } });
}

// 结构化 verifier 结果沿原公共 parser 的 1 MiB 边界；不缩小 stdout capture。
function resultJson(text: string): any {
  const value = strictJson(text), pending: unknown[] = [value];
  while (pending.length) {
    const item = pending.pop();
    if (typeof item === "number" && !Number.isFinite(item)) throw new ContractError("VERIFICATION_JSON_NONFINITE");
    if (item && typeof item === "object") for (const child of Object.values(item)) pending.push(child);
  }
  return value;
}

export function parseTestCounts(text: string, parser: VerificationBinding["parser"]): TestCounts | null {
  try {
    let counts: TestCounts;
    if (parser === "json") {
      const value = resultJson(text);
      counts = { tests: value.tests, passed: value.passed, failed: value.failed, skipped: value.skipped };
    } else if (parser === "pytest") {
      const summaries = text.split(/\r?\n/).map(line => line.replace(/^=+|=+$/g, "").trim())
        .filter(line => /(?:passed|failed|skipped|xfailed|xpassed|errors?)\b.*\bin [0-9.]+s/.test(line));
      if (summaries.length !== 1) return null;
      const values: Record<string, number> = {};
      for (const match of summaries[0].matchAll(/(\d+) (passed|failed|skipped|xfailed|xpassed|errors?)\b/g)) {
        if (values[match[2]] !== undefined) return null;
        values[match[2]] = Number(match[1]);
      }
      const passed = (values.passed ?? 0) + (values.xpassed ?? 0), failed = (values.failed ?? 0) + (values.error ?? 0) + (values.errors ?? 0);
      const skipped = (values.skipped ?? 0) + (values.xfailed ?? 0);
      counts = { tests: passed + failed + skipped, passed, failed, skipped };
    } else if (parser === "tap") {
      const read = (label: string): number => {
        const matches = [...text.matchAll(new RegExp(`^# ${label} (\\d+)\\s*$`, "gm"))];
        if (matches.length !== 1) throw new Error("ambiguous summary");
        return Number(matches[0][1]);
      };
      counts = { tests: read("tests"), passed: read("pass"), failed: read("fail"), skipped: read("skipped") };
    } else return null;
    if (Object.values(counts).some((value) => !Number.isSafeInteger(value) || value < 0)
      || counts.tests !== counts.passed + counts.failed + counts.skipped) return null;
    return counts;
  } catch { return null; }
}

export function parseTestResults(text: string, counts: TestCounts): Map<string, "passed" | "failed" | "skipped"> | null {
  try {
    const rows = resultJson(text).test_results;
    if (!Array.isArray(rows) || rows.length > 4096 || rows.length !== counts.tests) return null;
    const results = new Map<string, "passed" | "failed" | "skipped">(), totals = { passed: 0, failed: 0, skipped: 0 };
    for (const row of rows) {
      if (!row || Object.getPrototypeOf(row) !== Object.prototype || Object.keys(row).sort().join() !== "id,status"
          || typeof row.id !== "string" || !/^[a-zA-Z0-9_.:-]{1,200}$/.test(row.id) || results.has(row.id)
          || !["passed", "failed", "skipped"].includes(row.status)) return null;
      results.set(row.id, row.status); totals[row.status as keyof typeof totals]++;
    }
    return totals.passed === counts.passed && totals.failed === counts.failed && totals.skipped === counts.skipped ? results : null;
  } catch { return null; }
}

export type VerificationFacts = Pick<Awaited<ReturnType<typeof supervisedCommand>>, "stdout" | "truncated" | "timedOut" | "cancelled" | "spawnFailed" | "exitCode" | "terminationConfirmed" | "admissionError" | "lingering" | "launcherExitCode" | "started" | "terminalObserved">;

/** Deterministic acceptance policy over observed process/output facts; never infers missing facts. */
export function evaluateVerification(binding: Pick<VerificationBinding, "kind" | "parser" | "minimumTests" | "requiredTestIds">, execution: VerificationFacts) {
  const { stdout, truncated, timedOut, cancelled, spawnFailed, exitCode, terminationConfirmed } = execution;
  const counts = binding.kind === "tests" && !truncated ? parseTestCounts(stdout, binding.parser) : null;
  let status: VerificationResult["status"] = "passed", reason = "verified";
  if (!terminationConfirmed) { status = "unknown"; reason = "external_processes_not_confirmed_stopped"; }
  else if (execution.admissionError) { status = "failed"; reason = execution.admissionError; }
  else if (execution.lingering > 0) { status = "failed"; reason = "unfinished_descendants_terminated"; }
  else if (execution.launcherExitCode !== 0 && exitCode === 0) { status = "failed"; reason = "supervisor_failed"; }
  else if (spawnFailed || cancelled || timedOut || exitCode !== 0) {
    status = "failed"; reason = spawnFailed ? "spawn_failed" : cancelled ? "cancelled" : timedOut ? "timeout" : "nonzero_exit";
  } else if (!execution.started || !execution.terminalObserved) { status = "unknown"; reason = "command_terminal_not_observed"; }
  else if (truncated) { status = "unknown"; reason = "output_truncated"; }
  else if (binding.kind === "tests") {
    if (!counts) { status = "unknown"; reason = "test_count_unknown"; }
    else if (counts.tests < binding.minimumTests || counts.passed === 0 || counts.failed > 0) {
      status = "failed"; reason = "required_tests_not_passed";
    }
  }
  if (status === "passed" && binding.parser === "json") {
    try { resultJson(stdout); } catch { status = "unknown"; reason = "json_result_invalid"; }
  }
  if (status === "passed" && binding.requiredTestIds !== undefined) {
    const required = binding.requiredTestIds;
    const valid = binding.kind === "tests" && binding.parser === "json" && Array.isArray(required)
      && required.length > 0 && required.length <= 4096 && new Set(required).size === required.length
      && required.every(id => typeof id === "string" && /^[a-zA-Z0-9_.:-]{1,200}$/.test(id));
    const results = valid && counts && parseTestResults(stdout, counts);
    if (!results) { status = "unknown"; reason = valid ? "test_results_invalid" : "required_test_ids_invalid"; }
    else if (required.some(id => results.get(id) !== "passed")) {
      status = "failed"; reason = "required_test_ids_not_passed";
    }
  }
  let failureCategory: VerificationResult["failureCategory"] = status === "passed" ? null : spawnFailed ? "environment" : "unknown";
  if (status === "failed" && ["nonzero_exit", "required_tests_not_passed"].includes(reason) && binding.parser === "json"
    && !truncated && !timedOut && !cancelled && terminationConfirmed && execution.terminalObserved) {
    try { const reported = resultJson(stdout).failureCategory; if (reported === "implementation" || reported === "environment") failureCategory = reported; } catch { /* Unknown classifications never authorize escalation. */ }
  }
  return { counts, status, reason, failureCategory };
}

/** The caller resolves checkId from user-owned bindings; prompt text never becomes a shell command. */
export async function runVerification(checkId: string, bindings: Record<string, VerificationBinding>,
  target: { jobId: string; snapshot: string; cwd: string; contractDigest?: string; specVersion?: number | null; policyDigest?: string | null; inputSnapshotDigest?: string | null; evidenceOrigin?: EvidenceOrigin | null }, options: { signal?: AbortSignal; maxOutputBytes?: number; secrets?: string[]; killGraceMs?: number; onDispatch?: () => void } = {}): Promise<VerificationResult> {
  const fixedTarget = structuredClone(target);
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  const modern = runtime?.installed?.schema_version === 2 && runtime.installed.profile_id === "pi-full";
  const originValid = Number.isSafeInteger(fixedTarget.specVersion) && fixedTarget.specVersion! > 0
    && typeof fixedTarget.policyDigest === "string" && /^[a-f0-9]{64}$/.test(fixedTarget.policyDigest);
  if (!originValid && (modern || fixedTarget.specVersion != null || fixedTarget.policyDigest != null)) throw new ContractError("VERIFICATION_ORIGIN_REQUIRED");
  if(modern&&(typeof fixedTarget.inputSnapshotDigest!=="string"||!/^[a-f0-9]{64}$/.test(fixedTarget.inputSnapshotDigest)))throw new ContractError("INPUT_SNAPSHOT_ORIGIN_REQUIRED");
  const binding = bindings[checkId]&&structuredClone(bindings[checkId]);
  if (!binding) throw new ContractError("UNKNOWN_TRUSTED_CHECK");
  finiteInteger(binding.timeoutMs, 1, 2_147_000_000); finiteInteger(binding.minimumTests, 1);
  if (options.signal?.aborted) throw new ContractError("VERIFICATION_CANCELLED_BEFORE_START");
  const cwd = realpathSync(fixedTarget.cwd);
  const env = verificationEnvironment(binding);
  const maxBytes = options.maxOutputBytes ?? 1024 * 1024;
  finiteInteger(maxBytes, 1, 64 * 1024 * 1024);
  const killGrace = options.killGraceMs ?? 1000; finiteInteger(killGrace, 1, 60000);
  const startedAt = Date.now();
  const execution = await supervisedCommand(binding, cwd, env, { signal: options.signal, maxBytes, killGraceMs: killGrace, onDispatch: options.onDispatch, checkId, jobId: fixedTarget.jobId, contractDigest: fixedTarget.contractDigest });
  const endedAt = Date.now();
  const { stdout, stderr, truncated, exitCode, terminationConfirmed } = execution;
  const environmentDigest = verificationEnvironmentDigest(env, execution.supervisor);
  const { counts, status, reason, failureCategory } = evaluateVerification(binding, execution);
  const observedStdout=scrub(stdout,options.secrets,Number.MAX_SAFE_INTEGER);
  const executionFacts:VerificationFacts={stdout:observedStdout,truncated:execution.truncated,timedOut:execution.timedOut,cancelled:execution.cancelled,spawnFailed:execution.spawnFailed,exitCode:execution.exitCode,terminationConfirmed:execution.terminationConfirmed,admissionError:execution.admissionError,lingering:execution.lingering,launcherExitCode:execution.launcherExitCode,started:execution.started,terminalObserved:execution.terminalObserved};
  return { acceptanceBinding:{kind:binding.kind,parser:binding.parser,minimumTests:binding.minimumTests,...(binding.requiredTestIds?{requiredTestIds:binding.requiredTestIds}:{})},evidenceOrigin:fixedTarget.evidenceOrigin??null,invocationWindow:{startedAt,endedAt},executionFacts,inputSnapshotDigest:fixedTarget.inputSnapshotDigest??null,snapshotComparison:null,checkId, jobId: fixedTarget.jobId, snapshot: fixedTarget.snapshot, contractDigest: fixedTarget.contractDigest!, specVersion: originValid ? fixedTarget.specVersion! : null, policyDigest: originValid ? fixedTarget.policyDigest! : null, bindingDigest: digest(binding), environmentDigest, failureCategory,
    status, exitCode, reason, counts, stdout: scrub(stdout, options.secrets, Number.MAX_SAFE_INTEGER), stderr: scrub(stderr, options.secrets, Number.MAX_SAFE_INTEGER),
    truncated, terminationConfirmed, notSent: !execution.started, terminationCoverage: "agentcfg-supervisor", supervisor: execution.supervisor };
}
