import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createHash } from "node:crypto";

const require = createRequire(import.meta.url);
const root = process.argv[2] ? resolve(process.argv[2]) : dirname(require.resolve("pi-subagents"));
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
if (pkg.name !== "pi-subagents" || pkg.version !== "0.63.0") throw new Error("Unsupported pi-subagents version; no files modified.");
const path = join(root, "src/runs/shared/subagent-prompt-runtime.ts");
const before = '\tonRuntimeEvent("agent_start", () => {\n\t\tconst diagnostic = refreshChildToolDiagnostic(pi);\n\t\tif (diagnostic) throw new Error(formatChildToolDiagnostic(diagnostic));\n\t});';
const after = '\tonRuntimeEvent("agent_start", (_event: unknown, ctx?: ExtensionContext) => {\n\t\tconst diagnostic = refreshChildToolDiagnostic(pi);\n\t\tif (diagnostic) {\n\t\t\t// task-keeper-required-tools-abort-v1: lifecycle handler errors alone are not a request gate.\n\t\t\tctx?.abort();\n\t\t\tthrow new Error(formatChildToolDiagnostic(diagnostic));\n\t\t}\n\t});';
let source = readFileSync(path, "utf8");
if (!source.includes(after)) {
  if (source.split(before).length !== 2) throw new Error("Runtime source does not match reviewed patch context; no files modified.");
  writeFileSync(`${path}.task-keeper-original`, source, { flag: "wx" });
  source = source.replace(before, after); writeFileSync(path, source);
}
console.log(JSON.stringify({ package: pkg.name, version: pkg.version, patch: "required-tools-abort-v1", sha256: createHash("sha256").update(source).digest("hex") }));

// A scoped public adapter interface: the external owner must enforce retry admission and keep failure facts.
// AsyncLocalStorage prevents ordinary concurrent delegations from inheriting this policy.
const ownerPath = join(root, "src/api/recovery-owner.ts");
const ownerSource = `import { AsyncLocalStorage } from "node:async_hooks";
const key = Symbol.for("pi-subagents.recovery-owner.v2");
type Scope = { denied: number; onDenied?: () => unknown };
const registry = globalThis as typeof globalThis & { [key: symbol]: AsyncLocalStorage<Scope> };
const recoveryOwner = registry[key] ??= new AsyncLocalStorage<Scope>();
export function withRecoveryOwner<T>(run: () => T, onDenied?: () => unknown): T { return recoveryOwner.run({ denied: 0, onDenied }, run); }
export function hasRecoveryOwner(): boolean { return !!recoveryOwner.getStore(); }
export function recoveryOwnerDenials(): number { return recoveryOwner.getStore()?.denied ?? 0; }
export const recoveryOwnerVersion = "task-keeper-recovery-owner-v2";
const fetchKey = Symbol.for("pi-subagents.recovery-owner.fetch.v2");
const installed = globalThis as typeof globalThis & { [key: symbol]: unknown };
if (!installed[fetchKey]) {
  const original = globalThis.fetch;
  const guarded: typeof fetch = (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const scope = recoveryOwner.getStore();
    if (scope && method === "POST") {
      scope.denied++;
      try { const observation = scope.onDenied?.(); if (observation && typeof (observation as Promise<unknown>).then === "function") void Promise.resolve(observation).catch(() => {}); } catch { /* Observation failure must never open the gate. */ }
      return Promise.reject(new Error("Managed delegation cannot start an unbudgeted parent helper request"));
    }
    return original(input, init);
  };
  globalThis.fetch = guarded; installed[fetchKey] = guarded;
}
export function recoveryOwnerGateHealthy(): boolean { return installed[fetchKey] === globalThis.fetch; }
`;
writeFileSync(ownerPath, ownerSource);
const fallbackPath = join(root, "src/runs/shared/model-fallback.ts");
let fallback = readFileSync(fallbackPath, "utf8");
if (!fallback.includes("task-keeper-recovery-owner-v1")) {
  const changes = [
    ["function throwForExplicitModelExclusion(model: string): void {", "function throwForExplicitModelExclusion(model: string): void {\n\tif (hasRecoveryOwner()) return;"],
    ["const resolved = filterFallbackCandidates(candidates, { onExcluded: warnCachedExclusion });", "const resolved = hasRecoveryOwner() ? candidates : filterFallbackCandidates(candidates, { onExcluded: warnCachedExclusion });"],
    ["export function recordRetryableModelFailure(model: string | undefined, error: string | undefined): void {", "export function recordRetryableModelFailure(model: string | undefined, error: string | undefined): void {\n\tif (hasRecoveryOwner()) return;"],
  ];
  for (const [before] of changes) if (fallback.split(before).length !== 2) throw new Error("Recovery patch context does not match; refusing unsupported adapter.");
  writeFileSync(`${fallbackPath}.task-keeper-original`, fallback, { flag: "wx" });
  for (const [before, after] of changes) fallback = fallback.replace(before, after);
  fallback = 'import { hasRecoveryOwner } from "../../api/recovery-owner.ts"; // task-keeper-recovery-owner-v1\n' + fallback;
  writeFileSync(fallbackPath, fallback);
}
pkg.exports["./recovery-owner"] = "./src/api/recovery-owner.ts";
writeFileSync(join(root, "package.json"), JSON.stringify(pkg, null, 2) + "\n");
console.log(JSON.stringify({ patch: "recovery-owner-v1", sha256: createHash("sha256").update(fallback).digest("hex") }));

const entryPath = join(root, "index.ts");
let entry = readFileSync(entryPath, "utf8");
if (!entry.includes("task-keeper-adapter-probe-v1")) {
  const point = "\tregisterParentExtension?.(pi);";
  if (entry.split(point).length !== 2) throw new Error("Native entry does not match reviewed probe patch.");
  writeFileSync(`${entryPath}.task-keeper-original`, entry, { flag: "wx" });
  entry = entry.replace(point, point + `
  // task-keeper-adapter-probe-v1: identify the listener that will receive the actual delegation.
  if (registerParentExtension) pi.events.on("subagent:recovery-owner-probe", (request: unknown) => {
    const id = (request as { id?: string })?.id;
    if (typeof id === "string") pi.events.emit("subagent:recovery-owner-ready", { id, entry: import.meta.url, version: "task-keeper-recovery-owner-v1" });
  });`);
  writeFileSync(entryPath, entry);
}

// An active v1 listener must not masquerade as the newly instrumented helper gate.
const oldProbeVersion = 'version: "task-keeper-recovery-owner-v1"';
const newProbeVersion = 'version: "task-keeper-recovery-owner-v2"';
if (entry.includes(oldProbeVersion)) { entry = entry.replace(oldProbeVersion, newProbeVersion); writeFileSync(entryPath, entry); }
if (!entry.includes(newProbeVersion)) throw new Error("Missing v2 active-listener identity");
