export const STORE_SCHEMA_VERSION = 3;
export const MAINTENANCE_SCHEMA = `CREATE TABLE maintenance_history(
  id TEXT PRIMARY KEY, from_version INTEGER NOT NULL, to_version INTEGER NOT NULL,
  business_digest TEXT NOT NULL, backup TEXT NOT NULL);`;
export const BUSINESS_TABLES = [
    "meta",
    "owners",
    "intents",
    "events",
    "issues",
    "resources",
    "claims",
    "buckets",
    "requests",
    "records"
];
export const USAGE_SCHEMA = `CREATE INDEX IF NOT EXISTS usage_task_lookup ON records(json_extract(value,'$.taskId')) WHERE namespace='usage-links';
CREATE INDEX IF NOT EXISTS usage_started_lookup ON records(json_extract(value,'$.startedAt')) WHERE namespace='usage-tasks';`;
