import { test as nativeTest, type TestContext } from "node:test";
import nativeAssert from "node:assert/strict";
import { AsyncLocalStorage } from "node:async_hooks";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import type { AcceptanceWitness } from "../src/contracts/acceptance-plan.ts";

// Node starts this test worker's profiler before loading the test modules. It also
// propagates NODE_V8_COVERAGE into env-whitelisted children unless removed here.
// Fault-injected/killed Pi workers must not corrupt the parent's coverage JSON set.
if (process.env.NODE_TEST_CONTEXT) delete process.env.NODE_V8_COVERAGE;

interface Counts { assertions: number; attributed: Record<string, number>; matrixAssertions: Record<string, number>; acceptanceWitnesses: Record<string, AcceptanceWitness> }
const counts = new AsyncLocalStorage<Counts>();
const attribution = new AsyncLocalStorage<string>();
const matrixAttribution = new AsyncLocalStorage<string>();
const count = () => {
  const record = counts.getStore(); if (!record) return;
  record.assertions++;
  const id = attribution.getStore(); if (id) record.attributed[id] = (record.attributed[id] ?? 0) + 1;
  const variant = matrixAttribution.getStore(); if (variant) record.matrixAssertions[variant] = (record.matrixAssertions[variant] ?? 0) + 1;
};
/** Attribute actual assertion calls to one obligation; concurrent async blocks retain their own identity. */
export function evidence<T>(id: string, body: () => T): T {
  if (!counts.getStore()) throw new Error("Evidence must be recorded inside a test");
  if (!/^(?:T\d{2}|TK\d{2}|(?:CFG|EXE|EVD|REC|SCH|WFL|RTB|VAL)-\d{3})$/.test(id)) throw new Error("Invalid evidence ID");
  return attribution.run(id, body);
}
/** Explicit planned-variant attribution; a title or another variant's assertions earns no credit. */
export function matrixCase<T>(matrix: string, variant: string, body: () => T): T {
  if (!counts.getStore() || matrixAttribution.getStore()) throw new Error("Matrix evidence requires a non-nested test scope");
  if (![matrix, variant].every(value => /^[A-Za-z0-9.-]+$/.test(value))) throw new Error("Invalid matrix case identity");
  return matrixAttribution.run(`${matrix}:${variant}`, body);
}
/** Reuse matrix assertion counting, while retaining the actual independent observer artifact. */
export function acceptance<T>(caseId: string, variant: string, witness: AcceptanceWitness, body: () => T): T {
  const current = counts.getStore();
  if (!current || !/^AC\d{2}$/.test(caseId)) throw new Error("Invalid acceptance scope");
  const key = `r2-acceptance:${caseId}.${variant}`, previous = current.acceptanceWitnesses[key];
  if (previous && JSON.stringify(previous) !== JSON.stringify(witness)) throw new Error("Conflicting acceptance witness");
  current.acceptanceWitnesses[key] = witness;
  return matrixCase("r2-acceptance", `${caseId}.${variant}`, body);
}
let witnessSequence = 0;
export function observerArtifact(label: string, facts: unknown): string {
  if (!/^[a-zA-Z0-9.-]+$/.test(label)) throw new Error("Invalid observer label");
  const records = process.env.TASK_KEEPER_TEST_RECORD_DIR;
  if (!records) return "unrecorded-observer";
  const relative = `observers/${process.pid}-${++witnessSequence}-${label}.json`;
  const path = join(dirname(records), relative); mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, JSON.stringify(facts, null, 2) + "\n", { mode: 0o600 }); return relative;
}
export const assert: typeof nativeAssert = new Proxy(nativeAssert, {
  apply(target, receiver, args) { count(); return Reflect.apply(target, receiver, args); },
  get(target, key, receiver) {
    const value = Reflect.get(target, key, receiver);
    if (typeof value !== "function" || key === "AssertionError" || key === "Assert") return value;
    return (...args: unknown[]) => { count(); return Reflect.apply(value, target, args); };
  },
});
function record(suffix: string, value: unknown) {
  const directory = process.env.TASK_KEEPER_TEST_RECORD_DIR;
  if (!directory) return;
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  appendFileSync(join(directory, `${process.pid}${suffix}.jsonl`), JSON.stringify(value) + "\n", { mode: 0o600 });
}
export const test: typeof nativeTest = ((name: string, optionsOrBody: unknown, body?: (t: TestContext) => unknown) => {
  const options = typeof optionsOrBody === "function" ? {} : optionsOrBody;
  const callback = (typeof optionsOrBody === "function" ? optionsOrBody : body) as (t: TestContext) => unknown;
  const identity = { file: process.argv[1], name };
  record(".discovery", identity);
  return nativeTest(name, options as object, async (t) => {
    const current: Counts = { assertions: 0, attributed: {}, matrixAssertions: {}, acceptanceWitnesses: {} }; let status = "passed";
    const cleanups: Array<(context: TestContext) => unknown> = [];
    const context = new Proxy(t, { get(target, key) {
      const value = Reflect.get(target, key, target);
      if (key === "skip" || key === "todo") return (...args: unknown[]) => { status = "skipped"; return Reflect.apply(value, target, args); };
      if (key === "after") return (cleanup: (context: TestContext) => unknown) => { cleanups.push(cleanup); };
      return typeof value === "function" ? value.bind(target) : value;
    } });
    t.after(async () => {
      let failure: unknown;
      if (t.signal.aborted) status = "failed";
      for (const cleanup of cleanups) {
        try { await counts.run(current, () => cleanup(context)); }
        catch (error) { status = "failed"; failure ??= error; }
      }
      if (t.signal.aborted) status = "failed";
      record("", { ...identity, status, ...current });
      if (failure) throw failure;
    });
    try { await counts.run(current, () => callback(context)); }
    catch (error) { status = "failed"; throw error; }
  });
}) as typeof nativeTest;
