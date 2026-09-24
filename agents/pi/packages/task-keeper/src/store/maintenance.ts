import { bindDatabase, boundDatabaseName, legacyDatabaseName } from "./location.ts";
import { DatabaseSync } from "node:sqlite";
import { openSync, closeSync, fsyncSync, lstatSync, readFileSync, writeFileSync, realpathSync, existsSync, copyFileSync, renameSync, unlinkSync, chmodSync, linkSync } from "node:fs";
import { join, basename } from "node:path";
import { createHash } from "node:crypto";
import { canonical, digest, newId, ContractError } from "../contracts/primitives.ts";
import { processIdentity, originalProcessStopped, type ProcessIdentity } from "../adapters/process-identity.ts";
import { STORE_SCHEMA_VERSION, MAINTENANCE_SCHEMA, USAGE_SCHEMA, BUSINESS_TABLES } from "./schema.ts";

export type MaintenanceCut = "fenced" | "backed-up" | "schema-written" | "committed" | "before-release";
interface Journal {
  id: string; identity: string; source: string; from: number; to: number;
  businessDigest: string; process: ProcessIdentity; backup: string | null; backupHash: string | null;
  phase: "fenced" | "backed-up" | "committed" | "restoring";
}
const hashFile = (path: string) => createHash("sha256").update(readFileSync(path)).digest("hex");
function syncFile(path: string) { const fd = openSync(path, "r"); try { fsyncSync(fd); } finally { closeSync(fd); } }
function privateFile(path: string) {
  const st = lstatSync(path);
  if (!st.isFile() || st.isSymbolicLink() || st.nlink !== 1 || (st.mode & 0o077)) throw new ContractError("MAINTENANCE_FILE_NOT_PRIVATE");
}
function paths(root: string) {
  const st = lstatSync(root);
  if (!st.isDirectory() || st.isSymbolicLink() || (st.mode & 0o077)) throw new ContractError("STATE_DIRECTORY_NOT_PRIVATE");
  const directory = realpathSync(root), filename = boundDatabaseName(directory) ?? legacyDatabaseName(directory) ?? "runtime.db";
  bindDatabase(directory, filename);
  const path = join(directory, filename);
  return { directory, path, fence: `${path}.maintenance` };
}
function database(path: string) {
  privateFile(path);
  const db = new DatabaseSync(path); db.exec("PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;");
  return db;
}
function identity(db: DatabaseSync): string {
  const value = db.prepare("SELECT value FROM meta WHERE id='store-id'").get()?.value;
  if (typeof value !== "string") throw new ContractError("DATABASE_IDENTITY_MISSING"); return value;
}
export function businessDigest(db: DatabaseSync): string {
  return digest(BUSINESS_TABLES.map(table => [table, db.prepare(`SELECT * FROM ${table}`).all().map(row => canonical({ ...row })).sort()]));
}
function integrity(db: DatabaseSync) {
  if (db.prepare("PRAGMA integrity_check").get()?.integrity_check !== "ok" || db.prepare("PRAGMA foreign_key_check").all().length) throw new ContractError("DATABASE_INTEGRITY_FAILED");
}
function quiescent(db: DatabaseSync) {
  for (const owner of db.prepare("SELECT * FROM owners WHERE active=1").all()) {
    const row = db.prepare("SELECT value FROM records WHERE namespace='owner-process' AND id=?").get(owner.scope_id);
    const proof = row && JSON.parse(String(row.value));
    if (!proof || proof.token !== owner.token || proof.epoch !== owner.epoch || originalProcessStopped(proof.identity) !== true) throw new ContractError("MAINTENANCE_OWNER_NOT_STOPPED");
  }
}
function save(fence: string, journal: Journal, initial = false) {
  const temporary = `${fence}.${newId("write")}`;
  if (initial) {
    const fd = openSync(temporary, "wx", 0o600);
    try { writeFileSync(fd, canonical(journal)); fsyncSync(fd); } finally { closeSync(fd); }
    try { linkSync(temporary, fence); } finally { unlinkSync(temporary); }
  } else {
    writeFileSync(temporary, canonical(journal), { flag: "wx", mode: 0o600 }); syncFile(temporary); renameSync(temporary, fence);
  }
  syncFile(join(fence, ".."));
}
function load(path: string, fence: string): Journal {
  privateFile(fence); const journal: Journal = JSON.parse(readFileSync(fence, "utf8"));
  if (journal.source !== path || journal.to !== STORE_SCHEMA_VERSION || ![1, 2].includes(journal.from) || !journal.id.startsWith("migration-")) throw new ContractError("INVALID_MAINTENANCE_JOURNAL");
  const current = processIdentity();
  if (!current || (canonical(current) !== canonical(journal.process) && originalProcessStopped(journal.process) !== true)) throw new ContractError("MAINTENANCE_PROCESS_ACTIVE");
  if (journal.backup && basename(journal.backup) !== journal.backup) throw new ContractError("INVALID_BACKUP_PATH");
  return journal;
}
function release(directory: string, fence: string, journal: Journal, action: string) {
  const receipt = join(directory, `${journal.id}.${action}.json`);
  const content = canonical({ ...journal, action });
  if (existsSync(receipt)) { privateFile(receipt); if (readFileSync(receipt, "utf8") !== content) throw new ContractError("MAINTENANCE_RECEIPT_CONFLICT"); }
  else { writeFileSync(receipt, content, { flag: "wx", mode: 0o600 }); syncFile(receipt); }
  unlinkSync(fence); syncFile(directory);
}

/** Explicit offline maintenance. Active controllers must stop; no automatic migrations during package load. */
export function migrateStore(root: string, cut: (point: MaintenanceCut) => void = () => {}) {
  const { directory, path, fence } = paths(root);
  if (existsSync(fence)) throw new ContractError("MAINTENANCE_RECOVERY_REQUIRED");
  const db = database(path);
  try {
    integrity(db);
    const from = Number(db.prepare("PRAGMA user_version").get()!.user_version);
    if (from === STORE_SCHEMA_VERSION) return { changed: false, version: from };
    if (![1, 2].includes(from)) throw new ContractError("UNSUPPORTED_DATABASE_VERSION");
    const process = processIdentity(); if (!process) throw new ContractError("MAINTENANCE_PROCESS_UNKNOWN");
    db.exec("BEGIN IMMEDIATE");
    let journal: Journal;
    try {
      quiescent(db);
      journal = { id: newId("migration"), identity: identity(db), source: path, from, to: STORE_SCHEMA_VERSION,
        businessDigest: businessDigest(db), process, backup: null, backupHash: null, phase: "fenced" };
      save(fence, journal, true); db.exec("COMMIT");
    } catch (error) { db.exec("ROLLBACK"); throw error; }
    cut("fenced");
    const backup = `${journal.id}.backup.db`; db.prepare("VACUUM INTO ?").run(join(directory, backup));
    chmodSync(join(directory, backup), 0o600); syncFile(join(directory, backup));
    journal.backup = backup; journal.backupHash = hashFile(join(directory, backup)); journal.phase = "backed-up"; save(fence, journal); cut("backed-up");
    db.exec("BEGIN IMMEDIATE");
    try {
      if (businessDigest(db) !== journal.businessDigest) throw new ContractError("MAINTENANCE_SOURCE_CHANGED");
      db.exec(`${from === 1 ? MAINTENANCE_SCHEMA : ""} ${USAGE_SCHEMA} PRAGMA user_version=${STORE_SCHEMA_VERSION};`); cut("schema-written");
      db.prepare("INSERT INTO maintenance_history VALUES(?,?,?,?,?)").run(journal.id, from, STORE_SCHEMA_VERSION, journal.businessDigest, backup);
      integrity(db);
      if (businessDigest(db) !== journal.businessDigest) throw new ContractError("MIGRATION_CHANGED_BUSINESS_FACTS");
      db.exec("COMMIT");
    } catch (error) { db.exec("ROLLBACK"); throw error; }
    journal.phase = "committed"; save(fence, journal); cut("committed"); cut("before-release");
    release(directory, fence, journal, "upgraded");
    return { changed: true, version: STORE_SCHEMA_VERSION, backup: join(directory, backup) };
  } finally { db.close(); }
}

/** Finish an interrupted upgrade or restore its exact pre-upgrade DB. Fencing prevents intervening writes. */
export function recoverMaintenance(root: string, action: "finish" | "rollback") {
  const { directory, path, fence } = paths(root); const journal = load(path, fence);
  if (action === "finish") {
    const db = database(path);
    try {
      integrity(db); quiescent(db);
      if (identity(db) !== journal.identity || businessDigest(db) !== journal.businessDigest) throw new ContractError("MAINTENANCE_SOURCE_CHANGED");
      const version = Number(db.prepare("PRAGMA user_version").get()!.user_version);
      if (version !== STORE_SCHEMA_VERSION || !db.prepare("SELECT id FROM maintenance_history WHERE id=?").get(journal.id)) throw new ContractError("MIGRATION_NOT_COMMITTED");
    } finally { db.close(); }
    release(directory, fence, journal, "finished"); return { version: STORE_SCHEMA_VERSION };
  }
  if (!journal.backup || !journal.backupHash) {
    const db = database(path);
    try {
      integrity(db); quiescent(db);
      if (identity(db) !== journal.identity || businessDigest(db) !== journal.businessDigest || Number(db.prepare("PRAGMA user_version").get()!.user_version) !== journal.from) throw new ContractError("MAINTENANCE_SOURCE_CHANGED");
    } finally { db.close(); }
    release(directory, fence, journal, "unfenced"); return { version: journal.from };
  }
  const backup = join(directory, journal.backup); privateFile(backup);
  if (hashFile(backup) !== journal.backupHash) throw new ContractError("BACKUP_HASH_MISMATCH");
  const copy = database(backup);
  try {
    integrity(copy);
    if (identity(copy) !== journal.identity || businessDigest(copy) !== journal.businessDigest || Number(copy.prepare("PRAGMA user_version").get()!.user_version) !== journal.from) throw new ContractError("BACKUP_CONTENT_MISMATCH");
  } finally { copy.close(); }
  // Refuse rolling back newly written business facts even if somebody bypassed the maintenance guard.
  const current = database(path);
  try {
    if (identity(current) !== journal.identity || businessDigest(current) !== journal.businessDigest) throw new ContractError("MAINTENANCE_SOURCE_CHANGED");
    quiescent(current);
    const checkpoint = current.prepare("PRAGMA wal_checkpoint(TRUNCATE)").get();
    if (checkpoint?.busy !== 0) throw new ContractError("MAINTENANCE_CHECKPOINT_BUSY");
  } finally { current.close(); }
  journal.phase = "restoring"; save(fence, journal);
  const saved = join(directory, `${journal.id}.pre-restore.db`);
  if (!existsSync(saved)) { copyFileSync(path, saved); chmodSync(saved, 0o600); syncFile(saved); }
  const temporary = `${path}.${newId("restore")}`; copyFileSync(backup, temporary); chmodSync(temporary, 0o600); syncFile(temporary);
  renameSync(temporary, path); syncFile(directory);
  release(directory, fence, journal, "rolled-back"); return { version: journal.from };
}
