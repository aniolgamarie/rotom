import { pluginSettings } from "@agentcfg/pi-runtime/plugin-settings";
import { declaredRules } from "@agentcfg/pi-runtime/service-bindings";
import Type from "typebox";
import Schema from "typebox/schema";
import { parseDocument } from "yaml";
const FRONTMATTER_RE = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;
const RULE_TOOL_NAMES = new Set(["read", "edit", "write"]);
const RULE_SOURCE_SCHEMA = Type.Object({
    scope: Type.Union([Type.Literal("repo"), Type.Literal("user")]),
    kind: Type.Union([Type.Literal("pi"), Type.Literal("agents"), Type.Literal("claude")]),
});
export const RULE_CONFIG_SCHEMA = Type.Object({
    enabled: Type.Optional(Type.Boolean()),
    sources: Type.Array(RULE_SOURCE_SCHEMA),
    nudges: Type.Optional(Type.Object({ afterCommit: Type.Optional(Type.Boolean()) })),
});
export const RULE_CONFIG_PATCH_SCHEMA = Type.Partial(RULE_CONFIG_SCHEMA);
const RULE_CONFIG_VALIDATOR = Schema.Compile(RULE_CONFIG_SCHEMA);
const RULE_CONFIG_PATCH_VALIDATOR = Schema.Compile(RULE_CONFIG_PATCH_SCHEMA);
export const DEFAULT_RULE_SOURCES = [
    { scope: "repo", kind: "pi" },
    { scope: "repo", kind: "agents" },
    { scope: "repo", kind: "claude" },
    { scope: "user", kind: "pi" },
    { scope: "user", kind: "agents" },
    { scope: "user", kind: "claude" },
];
export function validateRuleConfigPatch(value) {
    if (!value || typeof value !== "object" || Object.keys(value).some(key => !["enabled", "sources", "nudges"].includes(key))
      || value.nudges && Object.keys(value.nudges).some(key => key !== "afterCommit")) return { reason: "unknown configuration field" };
    if (RULE_CONFIG_PATCH_VALIDATOR.Check(value))
        return { config: value };
    const [, errors] = RULE_CONFIG_PATCH_VALIDATOR.Errors(value);
    const first = errors[0];
    return { reason: first ? `${first.instancePath || "/"}: ${first.message}` : "schema validation failed" };
}
export async function loadRuleConfig(_cwd, _options = {}) {
  const value = pluginSettings("pi-rules", "rules");
  return { enabled: value.enabled ?? true, sources: [], nudgeAfterCommit: value.after_commit_nudge ?? false };
}
export async function discoverRules(_cwd, _options = {}) {
  if (Object.keys(_options).some(key => key !== "sources") || _options.sources?.length) throw new Error("RULES_SOURCE_OVERRIDE");
  const snapshot = await declaredRules();
  const rules = [];
  for (const item of snapshot.rules) {
    const parsed = await parseRuleFile(item.id, item.id, item.body);
    if (!parsed.rule) throw new Error("RULES_INVALID");
    rules.push(parsed.rule);
  }
  return { rules, diagnostics: [] };
}
export async function parseRuleFile(sourcePath, sourceLabel, content) {
    if (typeof content !== "string") throw new Error("RULES_BODY_REQUIRED");
    const frontmatter = content.match(FRONTMATTER_RE);
    if (!frontmatter) {
        if (/^\uFEFF?---(?:\r?\n|$)/.test(content)) {
            return { diagnostic: { sourceLabel, reason: "unclosed frontmatter" } };
        }
        return {
            rule: {
                id: sourcePath,
                sourcePath,
                sourceLabel,
                body: content.replace(/^\uFEFF/, ""),
            },
        };
    }
    let raw;
    try {
        const document = parseDocument(frontmatter[1] ?? "", { logLevel: "silent" });
        if (document.errors.length > 0) {
            return {
                diagnostic: {
                    sourceLabel,
                    reason: `invalid YAML: ${document.errors[0]?.message ?? "unknown error"}`,
                },
            };
        }
        raw = document.toJS();
    }
    catch (error) {
        return {
            diagnostic: {
                sourceLabel,
                reason: `invalid YAML: ${error instanceof Error ? error.message : String(error)}`,
            },
        };
    }
    if (raw !== null && (typeof raw !== "object" || Array.isArray(raw))) {
        return { diagnostic: { sourceLabel, reason: "frontmatter must be a mapping" } };
    }
    const record = (raw ?? {});
    if (Object.keys(record).some(key => !["paths", "events", "skills"].includes(key))) throw new Error("RULES_FIELD_UNKNOWN");
    const paths = normalizeStringList(record.paths, "paths", "glob");
    if (paths && "reason" in paths) {
        return { diagnostic: { sourceLabel, reason: paths.reason } };
    }
    const events = normalizeRuleEvents(record.events);
    if (events && "reason" in events) {
        return { diagnostic: { sourceLabel, reason: events.reason } };
    }
    const skills = normalizeStringList(record.skills, "skills", "skill name");
    if (skills && "reason" in skills) {
        return { diagnostic: { sourceLabel, reason: skills.reason } };
    }
    const rule = {
        id: sourcePath,
        sourcePath,
        sourceLabel,
        body: content.slice(frontmatter[0].length),
    };
    if (paths)
        rule.paths = paths;
    if (events)
        rule.events = events;
    if (skills)
        rule.skills = skills;
    return { rule };
}
function normalizeRuleEvents(raw) {
    if (raw === undefined)
        return undefined;
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
        return { reason: "events must be a mapping of Pi event names to filters" };
    }
    const record = raw;
    const unsupported = Object.keys(record).filter((name) => name !== "tool_call");
    if (unsupported.length > 0) {
        return { reason: `events contains unsupported Pi event: ${unsupported.join(", ")}` };
    }
    const toolNames = normalizeStringList(record.tool_call, "events.tool_call", "tool name");
    if (!toolNames)
        return { reason: "events must include tool_call" };
    if ("reason" in toolNames)
        return toolNames;
    if (!toolNames.every((name) => RULE_TOOL_NAMES.has(name))) {
        return { reason: "events.tool_call supports only read, edit, or write" };
    }
    return { tool_call: toolNames };
}
function normalizeStringList(raw, field, item) {
    if (raw === undefined)
        return undefined;
    const values = typeof raw === "string" ? [raw] : raw;
    if (!Array.isArray(values) || !values.every((value) => typeof value === "string")) {
        return { reason: `${field} must be a string or string list` };
    }
    const normalized = values.map((value) => value.trim());
    if (normalized.length === 0 || normalized.some((value) => value.length === 0)) {
        return { reason: `${field} must contain at least one non-empty ${item}` };
    }
    return [...new Set(normalized)];
}
