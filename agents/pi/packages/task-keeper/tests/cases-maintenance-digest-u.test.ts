import { test, assert } from "./recorded-test.ts";
import type { DatabaseSync } from "node:sqlite";
import { businessDigest } from "../src/store/maintenance.ts";

test("[U T76] maintenance fingerprint detects loss of intents, unknown requests and spent accounting", () => {
  // Adapter rows are unit inputs. The real migration/rollback transaction and
  // crash cuts remain in cases-migration-state-s and gap-g11-p.
  const rows: Record<string, Array<Record<string, unknown>>> = {
    intents: [{ id: "writer", status: "unknown", native_id: "original-native" }],
    requests: [{ id: "spent", state: "sent" }, { id: "uncertain", state: "unknown" }],
    buckets: [{ id: "work", used: 1, reserved: 1, ceiling: 2 }],
    claims: [{ intent_id: "writer", resource_id: "workspace", units: 1 }],
  };
  const fingerprint = (input: typeof rows) => businessDigest({ prepare(sql: string) {
    const table = /^SELECT \* FROM ([a-z_]+)$/.exec(sql)?.[1];
    assert.ok(table); return { all: () => structuredClone(input[table] ?? []) };
  } } as unknown as DatabaseSync);
  const before = structuredClone(rows), original = fingerprint(rows);
  assert.equal(fingerprint({ ...rows, requests: [...rows.requests].reverse() }), original);
  for (const table of ["intents", "requests", "buckets", "claims"]) {
    assert.notEqual(fingerprint({ ...rows, [table]: [] }), original, `lost ${table}`);
  }
  for (const change of [{ used: 0 }, { reserved: 0 }, { ceiling: 999 }])
    assert.notEqual(fingerprint({ ...rows, buckets: [{ ...rows.buckets[0], ...change }] }), original);
  assert.notEqual(fingerprint({ ...rows, requests: [rows.requests[0], { ...rows.requests[1], state: "not_sent" }] }), original);
  assert.deepEqual(rows, before);
});
