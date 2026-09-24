import { realpathSync, existsSync } from "node:fs";
import { resolve, dirname, basename, join } from "node:path";
import { Store } from "../store/database.ts";
import { digest, ContractError, identifier } from "../contracts/primitives.ts";

const fileKey = (path: string) => {
  let current = resolve(path); const suffix: string[] = [];
  while (!existsSync(current) && dirname(current) !== current) { suffix.unshift(basename(current)); current = dirname(current); }
  return digest(join(realpathSync(current), ...suffix));
};

/** Runtime/file/branch references must agree before a new budget namespace can be selected. */
export function workScopeIdentity(sessionId: string, references: readonly unknown[], isFork: boolean) {
  if (typeof sessionId !== "string" || !sessionId.length) throw new ContractError("WORK_SCOPE_SESSION_ID_UNKNOWN");
  const known = references.filter(value => value !== undefined);
  for (const value of known) try { identifier(value); } catch { throw new ContractError("WORK_SCOPE_REFERENCE_INVALID"); }
  const candidates = [...new Set(known as string[])];
  if (candidates.length > 1) throw new ContractError("WORK_SCOPE_IDENTITY_CONFLICT");
  if (!candidates.length && isFork) throw new ContractError("FORK_SCOPE_UNAVAILABLE");
  return { scopeId: candidates[0] ?? `managed-${digest(sessionId)}`, reused: candidates.length > 0 };
}

export function resolveWorkScope(store: Store, session: { id: string; file: string | null; parentFile?: string; originParentFile?: string; branchScope?: string; branchScopeExpected?: boolean; forkExpected?: boolean }) {
  const readReference = (namespace: string, id: string): unknown => {
    const row = store.db.prepare("SELECT value FROM records WHERE namespace=? AND id=?").get(namespace, id);
    if (!row) return undefined;
    let value;
    try { value = JSON.parse(String(row.value)); } catch { throw new ContractError("WORK_SCOPE_REFERENCE_INVALID"); }
    if (!value || typeof value !== "object" || Array.isArray(value) || value.scopeId === undefined) throw new ContractError("WORK_SCOPE_REFERENCE_INVALID");
    return value.scopeId;
  };
  if (session.branchScopeExpected && session.branchScope === undefined) throw new ContractError("WORK_SCOPE_REFERENCE_INVALID");
  const identity = workScopeIdentity(session.id, [readReference("session-scopes", session.id),
    session.file ? readReference("session-files", fileKey(session.file)) : undefined,
    session.parentFile ? readReference("session-files", fileKey(session.parentFile)) : undefined,
    session.originParentFile ? readReference("session-files", fileKey(session.originParentFile)) : undefined,
    session.branchScope], !!session.parentFile || !!session.originParentFile || session.forkExpected === true);
  if (identity.reused && !store.owner(identity.scopeId)) throw new ContractError("SCOPE_LEDGER_UNAVAILABLE");
  return identity.scopeId;
}
export function rememberWorkScope(store: Store, sessionId: string, file: string | null, scopeId: string): void {
  store.put("session-scopes", sessionId, { scopeId });
  if (file) store.put("session-files", fileKey(file), { scopeId, sessionId });
}
