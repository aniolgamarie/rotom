# Dependency and source notices

The runtime dependency manifests and integrity values are fixed in `package-lock.json`.

| Dependency | Role | Upstream license |
|---|---|---|
| Node.js built-in SQLite | Durable local coordination | Node.js distribution licenses |
| `@earendil-works/pi-coding-agent` 0.84.4 | Development runtime / host API contract | MIT |
| `pi-subagents` 0.63.0 | Conditional foreground child executor | MIT |
| Ajv 8.17.1 | Configuration schema validation | MIT |
| TypeBox 1.3.7 | Pi tool schema | MIT |
| TypeScript 5.9.3 | Development type checking | Apache-2.0 |
| jiti 2.7.0 | Test the same TypeScript-loading boundary as Pi | MIT |

Compatibility patch scripts operate on the user's installed dependency files and preserve the
upstream license. Original runtime source files are not vendored here. Installed dependencies
retain their own license files and copyright notices.

The v6 design/source index was supplied by the user. Its source identities and links are retained
for traceability; referenced research code, model weights and unpublished artifacts are not bundled.
