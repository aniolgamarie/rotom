import { readdirSync, existsSync, lstatSync, readFileSync, openSync, closeSync, writeFileSync, fsyncSync, linkSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { ContractError, newId, object } from "../contracts/primitives.ts";
const markerName = ".task-keeper-database.json";
export function databaseFilename(filename: string): string {
  if (!/^[a-zA-Z0-9_.-]+\.db$/.test(filename) || /^migration-.*\.(?:backup|pre-restore)\.db$/.test(filename)) throw new ContractError("INVALID_DATABASE_FILENAME");
  return filename;
}
export function boundDatabaseName(root: string): string | null {
  const path = join(root, markerName);
  if (!existsSync(path)) return null;
  const st = lstatSync(path);
  if (!st.isFile() || st.isSymbolicLink() || (st.mode & 0o077)) throw new ContractError("STATE_DATABASE_BINDING_NOT_PRIVATE");
  try {
    const record = object(JSON.parse(readFileSync(path, "utf8")), ["version", "filename"]);
    if (record.version !== 1 || typeof record.filename !== "string") throw new Error("invalid binding");
    return databaseFilename(record.filename);
  } catch { throw new ContractError("INVALID_STATE_DATABASE_BINDING"); }
}
/** Legacy database files are inspected by name only; maintenance snapshots never select a live ledger. */
export function legacyDatabaseName(root: string): string | null {
  const files = readdirSync(root);
  const markers = files.filter(name => name.endsWith(".db.identity")).map(name => name.slice(0, -".identity".length));
  const databases = files.filter(name => name.endsWith(".db") && !/^migration-.*\.(?:backup|pre-restore)\.db$/.test(name));
  const names = [...new Set([...markers, ...databases])];
  if (names.length > 1) throw new ContractError("STATE_DATABASE_CONFLICT", "Multiple live databases in one state directory require reconciliation");
  return names.length ? databaseFilename(names[0]) : null;
}
/** Persist one immutable database choice before a Store can create another ledger. */
export function bindDatabase(root: string, filename: string): void {
  databaseFilename(filename);
  const current = boundDatabaseName(root);
  if (current !== null) { if (current !== filename) throw new ContractError("STATE_DATABASE_CONFLICT"); return; }
  const legacy = legacyDatabaseName(root);
  if (legacy !== null && legacy !== filename) throw new ContractError("STATE_DATABASE_CONFLICT");
  const path = join(root, markerName), temporary = `${path}.${newId("bind")}`;
  const fd = openSync(temporary, "wx", 0o600);
  try {
    try { writeFileSync(fd, JSON.stringify({ version: 1, filename })); fsyncSync(fd); } finally { closeSync(fd); }
    try { linkSync(temporary, path); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  } finally { unlinkSync(temporary); }
  const directory = openSync(root, "r"); try { fsyncSync(directory); } finally { closeSync(directory); }
  if (boundDatabaseName(root) !== filename) throw new ContractError("STATE_DATABASE_CONFLICT");
}
