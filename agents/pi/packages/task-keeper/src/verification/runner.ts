import { supervisedCommand } from "./supervisor.ts";
import { realpathSync } from "node:fs";
import { digest, ContractError, finiteInteger } from "../contracts/primitives.ts";
import type { VerificationBinding } from "../config.ts";
import { scrub } from "../reliability/classifier.ts";

export interface TestCounts { tests: number; passed: number; failed: number; skipped: number }
export interface VerificationResult {
  checkId: string; jobId: string; snapshot: string; bindingDigest: string; environmentDigest: string;
  status: "passed" | "failed" | "unknown"; exitCode: number | null; reason: string;
  counts: TestCounts | null; stdout: string; stderr: string; truncated: boolean; terminationConfirmed: boolean;
  terminationCoverage: "agentcfg-supervisor";
  notSent: boolean;
  supervisor: Awaited<ReturnType<typeof supervisedCommand>>["supervisor"];
  failureCategory: "implementation" | "environment" | "unknown" | null;
}

export function verificationEnvironment(binding: VerificationBinding): NodeJS.ProcessEnv {
  return { PATH: process.env.PATH, LANG: "C.UTF-8", ...binding.environment };
}
export function verificationEnvironmentDigest(environment: NodeJS.ProcessEnv, supervisor: { executable: string; hash: string; engineHash: string }): string {
  const effective = Object.fromEntries(Object.entries(environment).filter(([, value]) => value !== undefined));
  return digest({ environment: { ...effective, NODE_NO_WARNINGS: "1" },
    supervisor: { executable: supervisor.executable, hash: supervisor.hash, engineHash: supervisor.engineHash } });
}

export function parseTestCounts(text: string, parser: VerificationBinding["parser"]): TestCounts | null {
  try {
    let counts: TestCounts;
    if (parser === "json") {
      const value = JSON.parse(text);
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

export type VerificationFacts = Pick<Awaited<ReturnType<typeof supervisedCommand>>, "stdout" | "truncated" | "timedOut" | "cancelled" | "spawnFailed" | "exitCode" | "terminationConfirmed" | "admissionError" | "lingering" | "launcherExitCode" | "started" | "terminalObserved">;

/** Deterministic acceptance policy over observed process/output facts; never infers missing facts. */
export function evaluateVerification(binding: Pick<VerificationBinding, "kind" | "parser" | "minimumTests">, execution: VerificationFacts) {
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
  let failureCategory: VerificationResult["failureCategory"] = status === "passed" ? null : spawnFailed ? "environment" : "unknown";
  if (status === "failed" && ["nonzero_exit", "required_tests_not_passed"].includes(reason) && binding.parser === "json"
    && !truncated && !timedOut && !cancelled && terminationConfirmed && execution.terminalObserved) {
    try { const reported = JSON.parse(stdout).failureCategory; if (reported === "implementation" || reported === "environment") failureCategory = reported; } catch { /* Unknown classifications never authorize escalation. */ }
  }
  return { counts, status, reason, failureCategory };
}

/** The caller resolves checkId from user-owned bindings; prompt text never becomes a shell command. */
export async function runVerification(checkId: string, bindings: Record<string, VerificationBinding>,
  target: { jobId: string; snapshot: string; cwd: string }, options: { signal?: AbortSignal; maxOutputBytes?: number; secrets?: string[]; killGraceMs?: number; onDispatch?: () => void } = {}): Promise<VerificationResult> {
  const binding = bindings[checkId];
  if (!binding) throw new ContractError("UNKNOWN_TRUSTED_CHECK");
  finiteInteger(binding.timeoutMs, 1, 2_147_000_000); finiteInteger(binding.minimumTests, 1);
  if (options.signal?.aborted) throw new ContractError("VERIFICATION_CANCELLED_BEFORE_START");
  const cwd = realpathSync(target.cwd);
  const env = verificationEnvironment(binding);
  const maxBytes = options.maxOutputBytes ?? 1024 * 1024;
  finiteInteger(maxBytes, 1, 64 * 1024 * 1024);
  const killGrace = options.killGraceMs ?? 1000; finiteInteger(killGrace, 1, 60000);
  const execution = await supervisedCommand(binding, cwd, env, { signal: options.signal, maxBytes, killGraceMs: killGrace, onDispatch: options.onDispatch, checkId, jobId: target.jobId });
  const { stdout, stderr, truncated, exitCode, terminationConfirmed } = execution;
  const environmentDigest = verificationEnvironmentDigest(env, execution.supervisor);
  const { counts, status, reason, failureCategory } = evaluateVerification(binding, execution);
  return { checkId, jobId: target.jobId, snapshot: target.snapshot, bindingDigest: digest(binding), environmentDigest, failureCategory,
    status, exitCode, reason, counts, stdout: scrub(stdout, options.secrets, Number.MAX_SAFE_INTEGER), stderr: scrub(stderr, options.secrets, Number.MAX_SAFE_INTEGER),
    truncated, terminationConfirmed, notSent: !execution.started, terminationCoverage: "agentcfg-supervisor", supervisor: execution.supervisor };
}
