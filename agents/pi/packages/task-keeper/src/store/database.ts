import { bindDatabase, databaseFilename } from "./location.ts";
import { ownerMatches } from "../contracts/ownership.ts";
import { intentDispatchable } from "../contracts/intents.ts";
import { DatabaseSync } from "node:sqlite";
import { mkdirSync, lstatSync, openSync, closeSync, realpathSync, existsSync, chmodSync, readFileSync, writeFileSync, linkSync, unlinkSync, fsyncSync } from "node:fs";
import { resolve, join } from "node:path";
import { ContractError, canonical, digest, finiteInteger, identifier, newId } from "../contracts/primitives.ts";
import { resourceClaimPlan } from "../contracts/resources.ts";
import { requestBudgetAvailable, requestSettlement, type RequestState } from "../contracts/budget.ts";

import { classifyEventAppend, eventSequenceGaps, type FactEvent } from "../contracts/events.ts";
export type { FactEvent } from "../contracts/events.ts";

import { STORE_SCHEMA_VERSION, MAINTENANCE_SCHEMA, USAGE_SCHEMA } from "./schema.ts";

export interface Owner { scopeId: string; token: string; epoch: number }
export interface Intent {
  id: string; scopeId: string; epoch: number; kind: string;
  status: "prepared" | "sent" | "acked" | "settled" | "not_sent" | "unknown";
  nativeId: string | null; payload: Record<string, unknown>;
}
type Row = Record<string, string | number | null>;

/** A private state root is the explicit coordination scope; no automatic lease-based takeover. */
export class Store {
  readonly db: DatabaseSync;
  readonly root: string;
  readonly path: string;
  private inTransaction = false;
  private fileIdentity: string | null = null;

  constructor(root: string, filename = "runtime.db") {
    databaseFilename(filename);
    const dir = resolve(root);
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    if (lstatSync(dir).isSymbolicLink() || (lstatSync(dir).mode & 0o077) !== 0) throw new ContractError("STATE_DIRECTORY_NOT_PRIVATE");
    this.root = realpathSync(dir);
    bindDatabase(this.root, filename);
    this.path = join(this.root, filename);
    this.assertWritable();
    const marker = `${this.path}.identity`;
    if (existsSync(marker) && (!existsSync(this.path) || lstatSync(this.path).size === 0)) throw new ContractError("DATABASE_LOST_NOT_FRESH");
    if (!existsSync(this.path)) {
      try { const fd = openSync(this.path, "wx", 0o600); closeSync(fd); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
    }
    const info = lstatSync(this.path);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || (info.mode & 0o077) !== 0) {
      throw new ContractError("STATE_FILE_NOT_PRIVATE");
    }
    this.fileIdentity = `${info.dev}:${info.ino}`;
    this.db = new DatabaseSync(this.path);
    try {
      this.db.exec("PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;");
      this.transaction(() => {
        const version = Number(this.db.prepare("PRAGMA user_version").get()!.user_version);
        if (version > STORE_SCHEMA_VERSION) throw new ContractError("UNSUPPORTED_DATABASE_VERSION");
        if (version > 0 && version < STORE_SCHEMA_VERSION) throw new ContractError("DATABASE_MIGRATION_REQUIRED");
        if (version === 0) {
          const count = Number(this.db.prepare("SELECT count(*) AS n FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").get()!.n);
          if (count) throw new ContractError("UNRECOGNIZED_DATABASE");
          this.db.exec(`
            CREATE TABLE meta(id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE owners(scope_id TEXT PRIMARY KEY, token TEXT NOT NULL, epoch INTEGER NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE intents(id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, epoch INTEGER NOT NULL, kind TEXT NOT NULL,
              status TEXT NOT NULL, native_id TEXT, payload TEXT NOT NULL);
            CREATE TABLE events(id TEXT PRIMARY KEY, producer TEXT NOT NULL, seq INTEGER NOT NULL, scope_id TEXT NOT NULL,
              kind TEXT NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL, UNIQUE(producer,seq));
            CREATE TABLE issues(id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE resources(id TEXT PRIMARY KEY, capacity INTEGER NOT NULL CHECK(capacity>=0));
            CREATE TABLE claims(resource_id TEXT NOT NULL, intent_id TEXT NOT NULL, units INTEGER NOT NULL CHECK(units>0),
              PRIMARY KEY(resource_id,intent_id), FOREIGN KEY(resource_id) REFERENCES resources(id), FOREIGN KEY(intent_id) REFERENCES intents(id));
            CREATE TABLE buckets(id TEXT PRIMARY KEY, ceiling INTEGER NOT NULL CHECK(ceiling>=0), used INTEGER NOT NULL DEFAULT 0,
              reserved INTEGER NOT NULL DEFAULT 0, CHECK(used>=0 AND reserved>=0));
            CREATE TABLE requests(id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, state TEXT NOT NULL, buckets TEXT NOT NULL,
              FOREIGN KEY(intent_id) REFERENCES intents(id));
            CREATE TABLE records(namespace TEXT NOT NULL, id TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(namespace,id));
            ${MAINTENANCE_SCHEMA}
            ${USAGE_SCHEMA}
            PRAGMA user_version=${STORE_SCHEMA_VERSION};
          `);
          this.db.prepare("INSERT INTO meta VALUES('store-id',?)").run(newId("store"));
        }
      });
      const identity = this.db.prepare("SELECT value FROM meta WHERE id='store-id'").get()?.value;
      if (typeof identity !== "string") throw new ContractError("DATABASE_IDENTITY_MISSING");
      for (const table of ["owners", "intents", "events", "issues", "resources", "claims", "buckets", "requests", "records", "maintenance_history"]) {
        if (!this.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(table)) throw new ContractError("DATABASE_SCHEMA_INCOMPLETE");
      }
      // Publish the identity only after WAL is ready. Reopened connections must
      // not issue a journal-mode change while another controller is writing.
      const journalDeadline = performance.now() + 5000, pause = new Int32Array(new SharedArrayBuffer(4));
      for (;;) {
        try {
          const mode = this.db.prepare("PRAGMA journal_mode").get()?.journal_mode;
          if (mode !== "wal" && this.db.prepare("PRAGMA journal_mode=WAL").get()?.journal_mode !== "wal")
            throw new ContractError("STATE_JOURNAL_UNAVAILABLE");
          this.db.exec("PRAGMA synchronous=FULL"); break;
        } catch (error) {
          const code = (error as { errcode?: number }).errcode;
          if (code === undefined || ![5, 6].includes(code & 0xff) || performance.now() >= journalDeadline) throw error;
          Atomics.wait(pause, 0, 0, 10);
        }
      }
      const markerValue = canonical({ filename, identity, version: 1 });
      if (!existsSync(marker)) {
        const temporary = `${marker}.${newId("tmp")}`;
        const fd = openSync(temporary, "wx", 0o600);
        try { writeFileSync(fd, markerValue); fsyncSync(fd); } finally { closeSync(fd); }
        try { linkSync(temporary, marker); }
        catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
        finally { unlinkSync(temporary); }
        const directory = openSync(this.root, "r");
        try { fsyncSync(directory); } finally { closeSync(directory); }
      }
      if (lstatSync(marker).isSymbolicLink() || readFileSync(marker, "utf8") !== markerValue) throw new ContractError("DATABASE_IDENTITY_MISMATCH");
    } catch (error) { this.db.close(); throw error; }
  }

  private assertWritable(): void {
    if (existsSync(`${this.path}.maintenance`)) throw new ContractError("STORE_MAINTENANCE_REQUIRED");
    if (this.fileIdentity !== null) {
      const info = lstatSync(this.path);
      if (`${info.dev}:${info.ino}` !== this.fileIdentity) throw new ContractError("DATABASE_REPLACED_REOPEN_REQUIRED");
    }
  }
  close(): void { this.db.close(); }
  transaction<T>(fn: () => T): T {
    if (this.inTransaction) throw new ContractError("NESTED_TRANSACTION");
    this.db.exec("BEGIN IMMEDIATE"); this.inTransaction = true;
    try {
      this.assertWritable();
      const result = fn();
      if (result && typeof (result as { then?: unknown }).then === "function") throw new ContractError("ASYNC_TRANSACTION");
      this.db.exec("COMMIT"); return result;
    } catch (error) { this.db.exec("ROLLBACK"); throw error; }
    finally { this.inTransaction = false; }
  }

  owner(scopeId: string): (Owner & { active: boolean }) | null {
    const row = this.db.prepare("SELECT * FROM owners WHERE scope_id=?").get(scopeId) as Row | undefined;
    return row ? { scopeId, token: String(row.token), epoch: Number(row.epoch), active: row.active === 1 } : null;
  }
  claimOwner(scopeId: string, token: string): Owner {
    identifier(scopeId); identifier(token);
    return this.transaction(() => {
      const old = this.owner(scopeId);
      if (old?.active && old.token !== token) throw new ContractError("OWNER_CONFLICT");
      if (old?.active) return old;
      const epoch = (old?.epoch ?? 0) + 1;
      this.db.prepare("INSERT INTO owners VALUES(?,?,?,1) ON CONFLICT(scope_id) DO UPDATE SET token=excluded.token,epoch=excluded.epoch,active=1").run(scopeId, token, epoch);
      return { scopeId, token, epoch };
    });
  }
  assertOwner(owner: Owner): void {
    this.assertWritable();
    const current = this.owner(owner.scopeId);
    if (!ownerMatches(owner, current)) throw new ContractError("CONTROL_REVOKED");
  }
  revokeOwner(owner: Owner): void {
    this.transaction(() => {
      this.assertOwner(owner);
      this.db.prepare("UPDATE owners SET active=0,epoch=epoch+1 WHERE scope_id=?").run(owner.scopeId);
      // Resource claims and unsettled requests deliberately survive revocation.
    });
  }

  prepare(owner: Owner, id: string, kind: string, payload: Record<string, unknown>,
    demands: Array<{ id: string; capacity: number; units: number }> = [], guard?: () => void): Intent {
    identifier(id); identifier(kind);
    for (const d of demands) { identifier(d.id); finiteInteger(d.capacity); finiteInteger(d.units, 1); }
    if (new Set(demands.map((d) => d.id)).size !== demands.length) throw new ContractError("DUPLICATE_RESOURCE");
    const prepare = () => {
      this.assertOwner(owner);
      guard?.();
      if (this.intent(id)) throw new ContractError("DUPLICATE_INTENT");
      if (this.issues(owner.scopeId).length) throw new ContractError("EVIDENCE_CONFLICT");
      if (this.sequenceGaps(owner.scopeId).length) throw new ContractError("EVIDENCE_GAP");
      const observations = demands.map(demand => {
        const resource = this.db.prepare("SELECT capacity FROM resources WHERE id=?").get(demand.id);
        const used = Number(this.db.prepare("SELECT coalesce(sum(units),0) AS n FROM claims WHERE resource_id=?").get(demand.id)!.n);
        return { id: demand.id, capacity: resource ? Number(resource.capacity) : null, used };
      });
      const plan = resourceClaimPlan(demands, observations);
      for (const demand of plan) this.db.prepare("INSERT INTO resources VALUES(?,?) ON CONFLICT(id) DO UPDATE SET capacity=min(capacity,excluded.capacity)").run(demand.id, demand.capacity);
      this.db.prepare("INSERT INTO intents VALUES(?,?,?,?,?,?,?)").run(id, owner.scopeId, owner.epoch, kind, "prepared", null, canonical(payload));
      for (const d of demands) this.db.prepare("INSERT INTO claims VALUES(?,?,?)").run(d.id, id, d.units);
      return this.intent(id)!;
    };
    return this.inTransaction ? prepare() : this.transaction(prepare);
  }
  intent(id: string): Intent | null {
    const row = this.db.prepare("SELECT * FROM intents WHERE id=?").get(id) as Row | undefined;
    return row ? { id, scopeId: String(row.scope_id), epoch: Number(row.epoch), kind: String(row.kind),
      status: row.status as Intent["status"], nativeId: row.native_id as string | null, payload: JSON.parse(String(row.payload)) } : null;
  }
  markSent(owner: Owner, id: string): void {
    this.transaction(() => {
      this.assertOwner(owner);
      const intent = this.intent(id);
      if (!intentDispatchable(owner, intent)) throw new ContractError("INTENT_NOT_DISPATCHABLE");
      this.db.prepare("UPDATE intents SET status='sent' WHERE id=?").run(id);
    });
  }
  acknowledge(id: string, nativeId: string): void {
    identifier(nativeId);
    this.transaction(() => {
      const intent = this.intent(id);
      if (!intent || !["sent", "unknown", "acked", "settled"].includes(intent.status)) throw new ContractError("INVALID_ACK");
      if (intent.nativeId && intent.nativeId !== nativeId) throw new ContractError("ACK_IDENTITY_CONFLICT");
      this.db.prepare("UPDATE intents SET status=?,native_id=? WHERE id=?").run(intent.status === "settled" ? "settled" : "acked", nativeId, id);
    });
  }
  settle(id: string, evidence: "terminated" | "not_sent" | "unknown", commit?: () => void): void {
    this.transaction(() => {
      const intent = this.intent(id);
      if (!intent) throw new ContractError("UNKNOWN_INTENT");
      if (["settled", "not_sent"].includes(intent.status)) {
        if ((intent.status === "settled" && evidence === "terminated") || (intent.status === "not_sent" && evidence === "not_sent")) return;
        throw new ContractError("CONFLICTING_SETTLEMENT");
      }
      if (evidence === "not_sent" && intent.nativeId) throw new ContractError("CONFLICTING_SETTLEMENT");
      const status = evidence === "terminated" ? "settled" : evidence;
      this.db.prepare("UPDATE intents SET status=? WHERE id=?").run(status, id);
      if (evidence !== "unknown") this.db.prepare("DELETE FROM claims WHERE intent_id=?").run(id);
      commit?.();
    });
  }
  claims(): Row[] { return this.db.prepare("SELECT * FROM claims ORDER BY resource_id,intent_id").all() as Row[]; }

  append(event: FactEvent): "inserted" | "duplicate" | "conflict" {
    for (const v of [event.id, event.producer, event.scopeId, event.kind]) identifier(v);
    finiteInteger(event.seq, 1);
    return this.transaction(() => {
      const rows = this.db.prepare("SELECT * FROM events WHERE id=? OR (producer=? AND seq=?)").all(event.id, event.producer, event.seq) as Row[];
      const decision = classifyEventAppend(event, rows.map(row => ({ hash: String(row.hash), scopeId: String(row.scope_id) })));
      if (decision.status === "duplicate") return "duplicate";
      if (decision.status === "conflict") {
        for (const scope of decision.conflictScopes) {
          this.db.prepare("INSERT INTO issues VALUES(?,?,?,?)").run(newId("issue"), scope, "event_conflict", event.id);
        }
        return "conflict";
      }
      this.db.prepare("INSERT INTO events VALUES(?,?,?,?,?,?,?)").run(event.id, event.producer, event.seq, event.scopeId, event.kind, canonical(event.payload), decision.hash);
      return "inserted";
    });
  }
  events(scopeId: string): FactEvent[] {
    return (this.db.prepare("SELECT * FROM events WHERE scope_id=? ORDER BY producer,seq").all(scopeId) as Row[]).map((row) => ({
      id: String(row.id), producer: String(row.producer), seq: Number(row.seq), scopeId,
      kind: String(row.kind), payload: JSON.parse(String(row.payload)),
    }));
  }
  sequenceGaps(scopeId: string): Array<{ producer: string; expected: number; actual: number }> {
    return eventSequenceGaps(this.events(scopeId));
  }
  issues(scopeId: string): Row[] { return this.db.prepare("SELECT * FROM issues WHERE scope_id=?").all(scopeId) as Row[]; }

  reserveRequest(owner: Owner, intentId: string, requestId: string, limits: Array<{ id: string; ceiling: number; minimumRemaining?: number }>): void {
    identifier(requestId);
    if (!limits.length || new Set(limits.map((l) => l.id)).size !== limits.length) throw new ContractError("INVALID_BUDGETS");
    for (const l of limits) { identifier(l.id); finiteInteger(l.ceiling); finiteInteger(l.minimumRemaining ?? 0); }
    this.transaction(() => {
      this.assertOwner(owner);
      const intent = this.intent(intentId);
      if (!intent || intent.scopeId !== owner.scopeId || intent.epoch !== owner.epoch
        || !["prepared", "sent", "acked"].includes(intent.status)) throw new ContractError("INVALID_INTENT");
      if (this.db.prepare("SELECT id FROM requests WHERE id=?").get(requestId)) throw new ContractError("DUPLICATE_REQUEST");
      for (const l of limits) {
        this.db.prepare("INSERT INTO buckets(id,ceiling) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET ceiling=min(ceiling,excluded.ceiling)").run(l.id, l.ceiling);
        const row = this.db.prepare("SELECT * FROM buckets WHERE id=?").get(l.id) as Row;
        if (!requestBudgetAvailable({ used: Number(row.used), reserved: Number(row.reserved), ceiling: Number(row.ceiling) }, l.minimumRemaining ?? 0)) throw new ContractError("BUDGET_DENIED");
      }
      for (const l of limits) this.db.prepare("UPDATE buckets SET reserved=reserved+1 WHERE id=?").run(l.id);
      this.db.prepare("INSERT INTO requests VALUES(?,?,?,?)").run(requestId, intentId, "reserved", canonical(limits.map((l) => l.id)));
    });
  }
  settleRequest(requestId: string, fact: "sent" | "not_sent" | "unknown"): void {
    this.transaction(() => {
      const row = this.db.prepare("SELECT * FROM requests WHERE id=?").get(requestId) as Row | undefined;
      if (!row) throw new ContractError("UNKNOWN_REQUEST");
      const transition = requestSettlement(row.state as RequestState, fact);
      if (!transition.changed) return;
      if (transition.reservedDelta !== 0) for (const id of JSON.parse(String(row.buckets)) as string[]) {
        this.db.prepare("UPDATE buckets SET reserved=reserved+?,used=used+? WHERE id=?").run(transition.reservedDelta, transition.usedDelta, id);
      }
      this.db.prepare("UPDATE requests SET state=? WHERE id=?").run(fact, requestId);
    });
  }
  bucket(id: string): Row | null { return this.db.prepare("SELECT * FROM buckets WHERE id=?").get(id) as Row ?? null; }
  request(id: string): Row | null { return this.db.prepare("SELECT * FROM requests WHERE id=?").get(id) as Row ?? null; }

  put(namespace: string, id: string, value: unknown): void {
    identifier(namespace); identifier(id);
    const put = () => this.db.prepare("INSERT INTO records VALUES(?,?,?) ON CONFLICT(namespace,id) DO UPDATE SET value=excluded.value").run(namespace, id, canonical(value));
    if (this.inTransaction) put(); else this.transaction(put);
  }
  has(namespace: string, id: string): boolean {
    return this.db.prepare("SELECT 1 FROM records WHERE namespace=? AND id=?").get(namespace, id) !== undefined;
  }
  get<T>(namespace: string, id: string): T | null {
    const row = this.db.prepare("SELECT value FROM records WHERE namespace=? AND id=?").get(namespace, id);
    return row ? JSON.parse(String(row.value)) as T : null;
  }
  list<T>(namespace: string): Array<{ id: string; value: T }> {
    return this.db.prepare("SELECT id,value FROM records WHERE namespace=? ORDER BY id").all(namespace).map((row) => ({ id: String(row.id), value: JSON.parse(String(row.value)) as T }));
  }
  backup(): string {
    this.assertWritable();
    if (this.inTransaction) throw new ContractError("BACKUP_INSIDE_TRANSACTION");
    const path = join(this.root, `${newId("backup")}.db`);
    this.db.prepare("VACUUM INTO ?").run(path);
    chmodSync(path, 0o600);
    return path;
  }
}
