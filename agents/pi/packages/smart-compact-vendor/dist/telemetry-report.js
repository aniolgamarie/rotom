// @bun
var __require = import.meta.require;

// src/constants.ts
var VERSION = "9.6.0";
var SETTLED_TRIGGER_COOLDOWN_MS = 10 * 60000;
var COMPACT_SYSTEM_PREFIX = "You are an expert conversation summarizer for a coding agent. " + "Produce structured markdown summaries. " + "Follow output format exactly. " + "Use EXACT names \u2014 never paraphrase code identifiers. " + "Trust deterministic extraction data over intuition.";
var PROFILES = {
  light: {
    summaryBudgetTokens: 1e4,
    keepRecentTokens: 30000,
    minChunkTokens: 800,
    maxChunkTokens: 12000,
    singlePassMaxTokens: 40000,
    batchMaxTokens: 30000
  },
  balanced: {
    summaryBudgetTokens: 6000,
    keepRecentTokens: 20000,
    minChunkTokens: 500,
    maxChunkTokens: 8000,
    singlePassMaxTokens: 30000,
    batchMaxTokens: 24000
  },
  aggressive: {
    summaryBudgetTokens: 3000,
    keepRecentTokens: 1e4,
    minChunkTokens: 300,
    maxChunkTokens: 6000,
    singlePassMaxTokens: 20000,
    batchMaxTokens: 18000
  }
};
var DEFAULT_CONFIG = {
  mode: "auto",
  profile: "balanced",
  profiles: PROFILES,
  summaryModel: null,
  segmentationModel: null,
  verificationModel: null,
  summaryThinkingLevel: "minimal",
  segmentationThinkingLevel: "minimal",
  agentToolAccess: "inherit",
  autoTrigger: true,
  showStatus: true,
  autoTriggerStrategy: "native-hook",
  autoTriggerTimeoutMs: 120000,
  backupEnabled: true,
  backupDir: "",
  minContextPercent: 60,
  requireApproval: true,
  scrubSecrets: true,
  scrubPii: false,
  maxLlmCalls: 8,
  maxLlmInputTokens: 0,
  codexMaxCallMs: 0,
  maxLatencyMs: 0,
  focusWeighting: true,
  zeroCallEnabled: true,
  contextGraphEnabled: true,
  telemetryChannel: "stable",
  adaptiveDamageFeedback: false,
  onlineDamageMonitor: true,
  pinPaths: []
};
var SINGLE_PASS_PREFIX = `Summarize this coding agent conversation. Produce ONE structured summary.
` + `
Rules for Accuracy:
` + `1. Session Type: read-only tool calls = REVIEW, not implementation
` + `2. Status: Check for user complaints before marking "Done"
` + `3. Exact Names: Quote specific variable/function/parameter names, don't paraphrase
` + `4. Files: Use the VERIFIED file lists above (deterministically extracted, zero hallucination risk)
` + `
Output EXACTLY this format:

` + `## Goal
[What the user is trying to accomplish]
` + `## Constraints & Preferences
- [CRITICAL: user requirements, preferences, constraints]
` + `## Progress
### Done
- [x] [Completed tasks with file references]
### In Progress
- [ ] [Current work state]
### Blocked
- [Issues]
` + `## Key Decisions
- **[Decision]**: [Rationale]
` + `## Files Modified
- [Verified list from deterministic extraction]
` + `## Files Deleted
- [Verified deleted paths from deterministic extraction]
` + `## Files Read
- [Verified list from deterministic extraction]
` + `## Next Steps
1. [What should happen next]
` + `## Critical Context
- [Specific data, patterns, info needed to continue]
- [Error patterns or gotchas]
` + `## Topics Covered
[Chronological bullet list with priority in brackets]
`;
var BATCH_PROMPT_PREFIX = `Summarize these conversation segments.

Rules for Accuracy:
` + `1. Use EXACT file paths from extraction data
` + `2. Status: only mark "done" if there's clear evidence (successful test run, user confirmation)
` + `3. Quote specific values, don't paraphrase code

` + `For EACH segment produce EXACTLY:
` + `### CHUNK {NUMBER}: {TOPIC_NAME}
` + `**Priority**: [critical|high|normal|low]
` + `**Summary**: [2-4 sentences: what happened, errors, code changes with paths]
` + `**Decisions**: [comma-separated, or "None"]
` + `**Modified**: [comma-separated paths, or "None"]
` + `**Deleted**: [comma-separated paths, or "None"]
` + `**Read**: [comma-separated paths, or "None"]
`;
var ASSEMBLY_PROMPT_PREFIX = `Merge these topic summaries into ONE coherent summary.

` + `## IMMUTABLE CONTEXT (do not modify or contradict these facts)
` + `These are deterministically verified from the original conversation. They take priority over ANY summary content below.

` + `Rules:
` + `1. Preserve ALL critical/high info. Condense normal, minimize low.
` + `2. Chronological order.
` + `3. The pre-processed data below is GROUND TRUTH \u2014 trust it over individual summaries.
` + `4. Files Modified list is deterministically verified \u2014 if a summary says a file was modified but it's NOT in the list above, omit it.
` + `5. Key Decisions below are verified \u2014 preserve them exactly, do not paraphrase the decision text.
` + `6. Do NOT fabricate file paths, function names, or error messages not present in the verified data.

` + `Format:
` + `## Goal
[Overall objective]
` + `## Constraints & Preferences
- [CRITICAL requirements, preferences, constraints]
` + `## Progress
### Done
- [x] [Completed tasks with file refs]
### In Progress
- [ ] [Current work state]
### Blocked
- [Issues]
` + `## Key Decisions
- **[Decision]**: [Rationale]
` + `## Files Modified
- [Verified deterministic list]
` + `## Files Deleted
- [Verified deterministic deleted paths]
` + `## Files Read
- [Verified deterministic list]
` + `## Next Steps
1. [What should happen next]
` + `## Critical Context
- [Data, patterns, info needed]
` + `## Topics Covered
[Chronological bullets with priority]
`;
var LOG_PREFIX = "[smart-compact]";
var BACKUP_MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000;
var FIVE_MINUTES_MS = 5 * 60 * 1000;
var ONE_HOUR_MS = 60 * 60 * 1000;
var SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;
var THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;
var ID_PREFIX = {
  PROJECT: "proj-",
  COMPACT_SESSION: "sc-",
  MULTI_TOOL_USE_SYNTHETIC: "mtu_",
  OPEN_LOOP: "loop-",
  DECISION: "decision-",
  ERROR: "error-"
};
var TUNING = {
  EMA_PREV: 0.7,
  EMA_SAMPLE: 0.3,
  CALIBRATION_CLAMP_MIN: 0.3,
  CALIBRATION_CLAMP_MAX: 3,
  CONFIDENCE_HIGH: 0.85,
  CONFIDENCE_MEDIUM: 0.8,
  CONFIDENCE_LOW: 0.6
};
var TRUNC = {
  MESSAGE: 300,
  ERROR_DETAIL: 500,
  DECISION_SUMMARY: 200,
  USER_RESPONSE: 300,
  CONSTRAINT_TEXT: 300,
  OPEN_LOOP_SUMMARY: 120,
  TIMELINE_EVENT: 150,
  TIMELINE_ERROR: 100,
  SNIPPET: 80,
  PREVIEW: 150,
  PREVIEW_MID: 200,
  DETAIL: 300,
  PREVIEW_LONG: 400,
  PREVIEW_XL: 500,
  PREVIOUS_SUMMARY: 12000,
  CONTINUITY_CAPSULE: 4000,
  CHUNK_FALLBACK: 180,
  DECISION_DETAIL: 60,
  TOPIC_LABEL: 100,
  PROJ_ID_HASH: 12,
  CONV_HASH: 8,
  RESULT_GAPS: 5,
  SESSION_ID_DISPLAY: 20,
  ERROR_SNIPPET: 30,
  TIMELINE_DISPLAY: 10,
  EXPLORE_RESULTS: 15,
  BACKUP_PREVIEW_LINES: 5,
  FINGERPRINT_SEG: 2
};
var LIKELY_ERROR_RE = /(?:command not found|no such file|permission denied|syntax error|cannot find|module not found|compilation error|build failed|test failed|^FAIL\b|ERROR:)/i;
var METRICS_BUFFER_MAX = 200;
var RUNTIME_LOG_MAX_BYTES = 5 * 1024 * 1024;
var EXPLORER_SYSTEM_PROMPT = `You are a conversation analyst. You have deterministic extraction data and can query the raw conversation using tools.

` + `Your job:
` + `1. Verify/enrich the extracted boundaries (merge, split, or add as needed)
` + `2. Identify cross-topic relationships
` + `3. Find implicit constraints (user tone, frustration, urgency)
` + `4. Assess completion status accurately
` + `5. Extract the narrative arc

` + `Use tools BEFORE forming conclusions. Finish within 3 tool rounds.

` + `After exploration, output ONLY a JSON object (no markdown):
` + '{"boundaries":[{"afterIndex":N,"topic":"...","priority":"critical|high|normal|low","confidence":0.0-1.0}],"mainGoal":"...","sessionType":"implementation|review|debugging|discussion","enrichedConstraints":[...],"crossReferences":[...],"statusAssessment":{"done":[...],"inProgress":[...],"blocked":[...]},"criticalContext":[...],"keyDecisions":[...]}';

// src/domain/telemetry.ts
function p95(values) {
  if (!values.length)
    return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)] ?? 0;
}
function stats(entries, damage) {
  const evidence = entries.filter((entry) => entry.status !== "dry-run");
  const successfulRuns = evidence.filter((entry) => entry.status === "success");
  const quality = successfulRuns.filter((entry) => typeof entry.verificationScore === "number");
  const appliedRunIds = new Set(successfulRuns.filter((entry) => typeof entry.runId === "string" && entry.runId.length >= 8).map((entry) => entry.runId));
  const observedScores = new Map;
  for (const observation of damage) {
    if (!observation.runId || !appliedRunIds.has(observation.runId) || typeof observation.damageScore !== "number" || !Number.isFinite(observation.damageScore))
      continue;
    observedScores.set(observation.runId, Math.max(observedScores.get(observation.runId) ?? 0, Math.max(0, Math.min(100, observation.damageScore))));
  }
  const damaging = [...observedScores.values()].filter((score) => score > 0).length;
  return {
    runs: entries.length,
    appliedRuns: evidence.length,
    successRate: evidence.length ? successfulRuns.length / evidence.length : 1,
    avgQuality: quality.length ? quality.reduce((sum, entry) => sum + (entry.verificationScore ?? 0), 0) / quality.length : null,
    qualityCoverage: evidence.length ? quality.length / evidence.length : 0,
    p95LatencyMs: p95(evidence.map((entry) => entry.durationMs ?? entry.avgLatency).filter(Number.isFinite)),
    avgTokens: evidence.length ? evidence.reduce((sum, entry) => sum + entry.totalInput + entry.totalCacheHit + (entry.totalCacheWrite ?? 0) + entry.totalOutput, 0) / evidence.length : 0,
    fallbackRate: evidence.length ? evidence.filter((entry) => entry.method === "heuristic" || Array.isArray(entry.providerRoutes) && entry.providerRoutes.some((route) => route.successes < route.calls)).length / evidence.length : 0,
    damageRate: observedScores.size ? damaging / observedScores.size : 0,
    damageCoverage: successfulRuns.length ? observedScores.size / successfulRuns.length : 0
  };
}
function roundStats(value) {
  return {
    ...value,
    successRate: Math.round(value.successRate * 1000) / 1000,
    avgQuality: value.avgQuality == null ? null : Math.round(value.avgQuality * 10) / 10,
    qualityCoverage: Math.round(value.qualityCoverage * 1000) / 1000,
    p95LatencyMs: Math.round(value.p95LatencyMs),
    avgTokens: Math.round(value.avgTokens),
    fallbackRate: Math.round(value.fallbackRate * 1000) / 1000,
    damageRate: Math.round(value.damageRate * 1000) / 1000,
    damageCoverage: Math.round(value.damageCoverage * 1000) / 1000
  };
}
function assessCanary(entries, damageEntries, options) {
  const minCanaryRuns = Math.max(5, options.minCanaryRuns ?? 20);
  const canaryEntries = entries.filter((entry) => entry.metricsSchemaVersion === 2 && entry.version === options.version && entry.releaseChannel === "canary").slice(-Math.max(100, minCanaryRuns));
  const baselineEntries = entries.filter((entry) => entry.metricsSchemaVersion === 2 && (entry.releaseChannel ?? "stable") === "stable").slice(-(options.baselineRuns ?? Math.max(50, minCanaryRuns * 2)));
  const baseline = stats(baselineEntries, damageEntries);
  const canary = stats(canaryEntries, damageEntries);
  const triggers = [];
  const failureBaseline = 1 - baseline.successRate;
  const failureCanary = 1 - canary.successRate;
  if (canary.appliedRuns >= 3 && (failureCanary > 0.050001 || failureCanary - failureBaseline >= 0.050001)) {
    triggers.push({
      metric: "failure-rate",
      baseline: failureBaseline,
      canary: failureCanary,
      threshold: failureCanary > 0.050001 ? ">5% absolute" : "+5pp regression"
    });
  }
  if (canary.avgQuality != null && (canary.avgQuality < 85 || baseline.avgQuality != null && baseline.avgQuality - canary.avgQuality >= 5)) {
    triggers.push({
      metric: "quality",
      baseline: baseline.avgQuality ?? 0,
      canary: canary.avgQuality,
      threshold: canary.avgQuality < 85 ? "<85 absolute" : "-5 points"
    });
  }
  if (baseline.p95LatencyMs >= 1000 && canary.p95LatencyMs >= baseline.p95LatencyMs * 1.5) {
    triggers.push({ metric: "latency", baseline: baseline.p95LatencyMs, canary: canary.p95LatencyMs, threshold: "+50% p95" });
  }
  if (baseline.avgTokens >= 1000 && canary.avgTokens >= baseline.avgTokens * 1.5) {
    triggers.push({ metric: "tokens", baseline: baseline.avgTokens, canary: canary.avgTokens, threshold: "+50%" });
  }
  if (canary.fallbackRate - baseline.fallbackRate >= 0.1) {
    triggers.push({ metric: "fallback", baseline: baseline.fallbackRate, canary: canary.fallbackRate, threshold: "+10pp" });
  }
  if (canary.damageRate - baseline.damageRate >= 0.1) {
    triggers.push({ metric: "damage", baseline: baseline.damageRate, canary: canary.damageRate, threshold: "+10pp" });
  }
  const canarySampleAdequacy = Math.min(1, canary.appliedRuns / minCanaryRuns);
  const baselineSampleAdequacy = Math.min(1, baseline.appliedRuns / Math.max(20, minCanaryRuns));
  const dataConfidence = Math.round(100 * (canarySampleAdequacy * 0.25 + baselineSampleAdequacy * 0.15 + canary.qualityCoverage * canarySampleAdequacy * 0.2 + canary.damageCoverage * canarySampleAdequacy * 0.2 + baseline.damageCoverage * baselineSampleAdequacy * 0.2));
  const reasons = [];
  let decision = "hold";
  if (triggers.length && canary.appliedRuns >= 3) {
    decision = "rollback";
    reasons.push(...triggers.map((trigger) => trigger.metric + " crossed " + trigger.threshold));
  } else if (canary.appliedRuns < minCanaryRuns) {
    reasons.push("need " + (minCanaryRuns - canary.appliedRuns) + " more canary runs with applied outcomes");
  } else if (baseline.appliedRuns < Math.max(20, minCanaryRuns)) {
    reasons.push("stable baseline is too small");
  } else if (canary.qualityCoverage < 0.7) {
    reasons.push("schema-v2 quality coverage is below 70%");
  } else if (canary.damageCoverage < 0.7) {
    reasons.push("correlated canary damage-observation coverage is below 70%");
  } else if (baseline.damageCoverage < 0.7) {
    reasons.push("correlated stable damage-observation coverage is below 70%");
  } else if ((canary.avgQuality ?? 0) < 85) {
    reasons.push("absolute verifier quality is below 85");
  } else if (canary.successRate < 0.949999) {
    reasons.push("absolute success rate is below 95%");
  } else {
    decision = "promote";
    reasons.push("sample, absolute quality, reliability, latency, token, fallback, and damage gates passed");
  }
  return {
    version: options.version,
    decision,
    dataConfidence,
    baseline: roundStats(baseline),
    canary: roundStats(canary),
    triggers,
    reasons
  };
}
function safeMetricLabel(value, fallback) {
  if (typeof value !== "string" || !/^[\w./:@+-]{1,160}$/.test(value))
    return fallback;
  return value;
}
var TELEMETRY_FAILURE_KINDS = new Set([
  "cancelled",
  "timeout",
  "rate-limit",
  "authentication",
  "budget",
  "output-limit",
  "provider",
  "persistence",
  "validation",
  "verification",
  "yield",
  "internal"
]);
function isTelemetryFailureKind(value) {
  return typeof value === "string" && TELEMETRY_FAILURE_KINDS.has(value);
}
function buildPrivacySafeTelemetry(entries, damageEntries, options) {
  const groups = new Map;
  const failures = {};
  for (const entry of entries) {
    const version = safeMetricLabel(entry.version, "legacy");
    const channel = entry.releaseChannel === "canary" ? "canary" : "stable";
    const provider = safeMetricLabel(entry.provider, "unknown");
    const rawModel = safeMetricLabel(entry.model, "unknown");
    const model = rawModel.startsWith(provider + "/") ? rawModel.slice(provider.length + 1) : rawModel;
    const key = [version, channel, provider, model].join("\x00");
    const group = groups.get(key) ?? {
      version,
      channel,
      provider,
      model,
      runs: 0,
      successes: 0,
      quality: 0,
      qualityRuns: 0,
      latency: 0,
      input: 0,
      output: 0
    };
    group.runs++;
    if (entry.status === "success" || entry.status === "dry-run")
      group.successes++;
    if (entry.metricsSchemaVersion === 2 && typeof entry.verificationScore === "number") {
      group.quality += entry.verificationScore;
      group.qualityRuns++;
    }
    group.latency += entry.avgLatency;
    group.input += entry.totalInput + entry.totalCacheHit + (entry.totalCacheWrite ?? 0);
    group.output += entry.totalOutput;
    groups.set(key, group);
    if (isTelemetryFailureKind(entry.failureKind)) {
      failures[entry.failureKind] = (failures[entry.failureKind] ?? 0) + 1;
    }
  }
  const aggregates = [...groups.values()].map((group) => ({
    version: group.version,
    channel: group.channel,
    provider: group.provider,
    model: group.model,
    runs: group.runs,
    successes: group.successes,
    avgQuality: group.qualityRuns ? Math.round(group.quality / group.qualityRuns * 10) / 10 : null,
    avgLatencyMs: group.runs ? Math.round(group.latency / group.runs) : 0,
    inputTokens: group.input,
    outputTokens: group.output
  })).sort((a, b) => b.runs - a.runs || a.version.localeCompare(b.version));
  return {
    generatedAt: new Date().toISOString(),
    totalRuns: entries.length,
    aggregates,
    failures,
    canary: assessCanary(entries, damageEntries, options),
    privacy: "aggregate-only; no session ids, project ids, prompts, summaries, paths, or error text"
  };
}
function formatPrivacySafeTelemetry(report) {
  const lines = [
    "# Smart Compact Telemetry",
    "",
    "Privacy: " + report.privacy + ".",
    "",
    "| Version | Channel | Provider/model | Runs | Success | Quality | Latency | Input | Output |",
    "|---|---|---|---:|---:|---:|---:|---:|---:|"
  ];
  for (const item of report.aggregates) {
    lines.push("| " + item.version + " | " + item.channel + " | " + item.provider + "/" + item.model + " | " + item.runs + " | " + item.successes + "/" + item.runs + " | " + (item.avgQuality == null ? "n/a" : item.avgQuality.toFixed(1)) + " | " + item.avgLatencyMs + "ms | " + item.inputTokens + " | " + item.outputTokens + " |");
  }
  lines.push("", "## Canary: " + report.canary.decision.toUpperCase() + " (data confidence " + report.canary.dataConfidence + "%)", "");
  const baseline = report.canary.baseline;
  const canary = report.canary.canary;
  lines.push("| Gate | Stable baseline | Canary |", "|---|---:|---:|", "| Runs (total/applied) | " + baseline.runs + "/" + baseline.appliedRuns + " | " + canary.runs + "/" + canary.appliedRuns + " |", "| Success | " + Math.round(baseline.successRate * 100) + "% | " + Math.round(canary.successRate * 100) + "% |", "| Verify quality | " + (baseline.avgQuality ?? "n/a") + " | " + (canary.avgQuality ?? "n/a") + " |", "| p95 duration | " + baseline.p95LatencyMs + "ms | " + canary.p95LatencyMs + "ms |", "| Avg tokens | " + baseline.avgTokens + " | " + canary.avgTokens + " |", "| Fallback | " + Math.round(baseline.fallbackRate * 100) + "% | " + Math.round(canary.fallbackRate * 100) + "% |", "| Damage | " + Math.round(baseline.damageRate * 100) + "% | " + Math.round(canary.damageRate * 100) + "% |", "| Damage observed | " + Math.round(baseline.damageCoverage * 100) + "% | " + Math.round(canary.damageCoverage * 100) + "% |", "");
  for (const reason of report.canary.reasons)
    lines.push("- " + reason);
  const failureText = Object.entries(report.failures).map(([kind, count]) => kind + "=" + count).join(", ");
  lines.push("", "Failures: " + (failureText || "none classified"));
  return lines.join(`
`);
}

// src/infra/fs.ts
import fs from "fs";

// src/utils/logger.ts
var DEBUG = process.env.DEBUG?.includes("smart-compact") ?? false;
function warn(msg, err) {
  const detail = err instanceof Error ? err.message : err ?? "";
  console.error(LOG_PREFIX + " " + msg + (detail ? ": " + detail : ""));
}

// src/infra/fs.ts
function readJsonlTail(target, limit, maxBytes = 512 * 1024) {
  if (limit <= 0 || !fs.existsSync(target))
    return [];
  const stat = fs.statSync(target);
  const length = Math.min(stat.size, maxBytes);
  const buffer = Buffer.alloc(length);
  const fd = fs.openSync(target, "r");
  try {
    fs.readSync(fd, buffer, 0, length, stat.size - length);
  } finally {
    fs.closeSync(fd);
  }
  let text = buffer.toString("utf8");
  if (stat.size > length) {
    const newline = text.indexOf(`
`);
    text = newline >= 0 ? text.slice(newline + 1) : "";
  }
  const values = [];
  for (const line of text.split(`
`)) {
    if (!line)
      continue;
    try {
      values.push(JSON.parse(line));
    } catch {}
  }
  return values.slice(-limit);
}

// src/infra/paths.ts
import path from "path";
import os from "os";
function home() {
  const configured = process.env.HOME?.trim() || process.env.USERPROFILE?.trim();
  return configured || os.homedir();
}
function piAgentDir() {
  return path.join(home(), ".pi", "agent");
}
function cacheDir() {
  return path.join(piAgentDir(), ".cache");
}
function smartCompactCacheDir() {
  return path.join(cacheDir(), "smart-compact");
}
function metricsLogFile() {
  return path.join(cacheDir(), "compact-metrics.jsonl");
}
function damageReportsFile() {
  return path.join(smartCompactCacheDir(), "damage-reports.jsonl");
}

// src/utils/cache.ts
import fs2 from "fs";

// src/utils/lru.ts
function lruGet(m, key) {
  if (!m.has(key))
    return;
  const v = m.get(key);
  m.delete(key);
  m.set(key, v);
  return v;
}
function lruSet(m, key, value, max) {
  if (m.has(key))
    m.delete(key);
  m.set(key, value);
  while (m.size > max) {
    const oldest = m.keys().next().value;
    if (oldest === undefined)
      break;
    m.delete(oldest);
  }
}

// src/utils/tokens.ts
var PROVIDER_MAP = {
  "zai-anthropic": {
    maxOutputTokens: 8192,
    supportsTools: "probe",
    jsonReliability: "high",
    instructionFollowing: "high",
    tokenRatioEstimate: 3.5,
    concurrencyLimit: 3,
    cacheStrategy: "anthropic",
    timeoutMultiplier: 1.2,
    singlePassTokenMultiplier: 1,
    multimodal: "metadata-only"
  },
  "kimi-coding": {
    maxOutputTokens: 8192,
    supportsTools: "probe",
    jsonReliability: "high",
    instructionFollowing: "high",
    tokenRatioEstimate: 3.5,
    concurrencyLimit: 2,
    cacheStrategy: "anthropic",
    timeoutMultiplier: 1.5,
    singlePassTokenMultiplier: 0.95,
    multimodal: "metadata-only"
  },
  anthropic: {
    maxOutputTokens: 8192,
    supportsTools: true,
    jsonReliability: "high",
    instructionFollowing: "high",
    tokenRatioEstimate: 3.5,
    concurrencyLimit: 3,
    cacheStrategy: "anthropic",
    timeoutMultiplier: 1.2,
    singlePassTokenMultiplier: 1,
    multimodal: "native"
  },
  openai: {
    maxOutputTokens: 16384,
    supportsTools: true,
    jsonReliability: "high",
    instructionFollowing: "high",
    tokenRatioEstimate: 4,
    concurrencyLimit: 5,
    cacheStrategy: "openai",
    timeoutMultiplier: 1,
    singlePassTokenMultiplier: 1.15,
    multimodal: "native"
  },
  google: {
    maxOutputTokens: 8192,
    supportsTools: true,
    jsonReliability: "high",
    instructionFollowing: "high",
    tokenRatioEstimate: 3.8,
    concurrencyLimit: 3,
    cacheStrategy: "openai",
    timeoutMultiplier: 1.15,
    singlePassTokenMultiplier: 1.1,
    multimodal: "native"
  },
  deepseek: {
    maxOutputTokens: 8192,
    supportsTools: true,
    jsonReliability: "medium",
    instructionFollowing: "medium",
    tokenRatioEstimate: 3.6,
    concurrencyLimit: 2,
    cacheStrategy: "none",
    timeoutMultiplier: 1.5,
    singlePassTokenMultiplier: 0.85,
    multimodal: "metadata-only"
  },
  minimax: {
    maxOutputTokens: 4096,
    supportsTools: "probe",
    jsonReliability: "medium",
    instructionFollowing: "medium",
    tokenRatioEstimate: 3.8,
    concurrencyLimit: 2,
    cacheStrategy: "anthropic",
    timeoutMultiplier: 1.6,
    singlePassTokenMultiplier: 0.8,
    multimodal: "metadata-only"
  },
  "xiaomi-token-plan": {
    maxOutputTokens: 8192,
    supportsTools: "probe",
    jsonReliability: "medium",
    instructionFollowing: "medium",
    tokenRatioEstimate: 3.3,
    concurrencyLimit: 2,
    cacheStrategy: "openai",
    timeoutMultiplier: 1.35,
    singlePassTokenMultiplier: 0.9,
    multimodal: "metadata-only"
  },
  "xiaomi-mimo": {
    maxOutputTokens: 8192,
    supportsTools: "probe",
    jsonReliability: "medium",
    instructionFollowing: "medium",
    tokenRatioEstimate: 3.3,
    concurrencyLimit: 2,
    cacheStrategy: "anthropic",
    timeoutMultiplier: 1.35,
    singlePassTokenMultiplier: 0.9,
    multimodal: "metadata-only"
  },
  crofai: {
    maxOutputTokens: 8192,
    supportsTools: "probe",
    jsonReliability: "medium",
    instructionFollowing: "medium",
    tokenRatioEstimate: 3.8,
    concurrencyLimit: 3,
    cacheStrategy: "none",
    timeoutMultiplier: 1.2,
    singlePassTokenMultiplier: 0.95,
    multimodal: "metadata-only"
  },
  mistral: {
    maxOutputTokens: 8192,
    supportsTools: true,
    jsonReliability: "high",
    instructionFollowing: "high",
    tokenRatioEstimate: 3.5,
    concurrencyLimit: 3,
    cacheStrategy: "openai",
    timeoutMultiplier: 1.2,
    singlePassTokenMultiplier: 1,
    multimodal: "metadata-only"
  },
  xai: {
    maxOutputTokens: 8192,
    supportsTools: true,
    jsonReliability: "medium",
    instructionFollowing: "high",
    tokenRatioEstimate: 3.8,
    concurrencyLimit: 3,
    cacheStrategy: "openai",
    timeoutMultiplier: 1.2,
    singlePassTokenMultiplier: 1,
    multimodal: "native"
  }
};
var PROVIDER_ALIASES = [
  { pattern: /anthropic/i, provider: "anthropic" },
  { pattern: /kimi/i, provider: "kimi-coding" },
  { pattern: /zai/i, provider: "zai-anthropic" },
  { pattern: /openai/i, provider: "openai" },
  { pattern: /gpt/i, provider: "openai" },
  { pattern: /google|gemini/i, provider: "google" },
  { pattern: /deepseek/i, provider: "deepseek" },
  { pattern: /minimax/i, provider: "minimax" },
  { pattern: /xiaomi-mimo/i, provider: "xiaomi-mimo" },
  { pattern: /xiaomi/i, provider: "xiaomi-token-plan" },
  { pattern: /crofai/i, provider: "crofai" },
  { pattern: /mistral/i, provider: "mistral" },
  { pattern: /xai|grok/i, provider: "xai" }
];
var DEFAULT_CAPS = {
  maxOutputTokens: 8192,
  supportsTools: "probe",
  jsonReliability: "medium",
  instructionFollowing: "medium",
  tokenRatioEstimate: 3.8,
  concurrencyLimit: 2,
  cacheStrategy: "none",
  timeoutMultiplier: 1.35,
  singlePassTokenMultiplier: 0.9,
  multimodal: "metadata-only"
};
function getProviderCaps(provider) {
  if (PROVIDER_MAP[provider])
    return PROVIDER_MAP[provider];
  for (const { pattern, provider: key } of PROVIDER_ALIASES) {
    if (pattern.test(provider))
      return PROVIDER_MAP[key] ?? DEFAULT_CAPS;
  }
  return DEFAULT_CAPS;
}
class TokenCalibrationStore {
  maxEntries;
  factors = new Map;
  constructor(maxEntries = 128) {
    this.maxEntries = maxEntries;
  }
  clear() {
    this.factors.clear();
  }
  get(provider, model) {
    if (!provider)
      return 1;
    const exactKey = calibrationKey(provider, model);
    const exact = lruGet(this.factors, exactKey);
    if (exact !== undefined)
      return exact;
    return lruGet(this.factors, calibrationKey(provider)) ?? 1;
  }
  calibrate(estimated, actual, provider, model) {
    if (actual <= 0 || estimated <= 0 || !provider)
      return;
    const key = calibrationKey(provider, model);
    const prev = lruGet(this.factors, key) ?? 1;
    const target = prev * actual / estimated;
    const clamped = Math.max(TUNING.CALIBRATION_CLAMP_MIN, Math.min(TUNING.CALIBRATION_CLAMP_MAX, target));
    lruSet(this.factors, key, prev * TUNING.EMA_PREV + clamped * TUNING.EMA_SAMPLE, Math.max(1, this.maxEntries));
  }
  size() {
    return this.factors.size;
  }
}
var _fallbackCalibration = new TokenCalibrationStore;
function calibrationKey(provider, model) {
  return model ? provider + "/" + model : provider + "/*";
}

// src/utils/type-guards.ts
function isRecord(value) {
  return typeof value === "object" && value !== null;
}
function isTextBlock(c) {
  return isRecord(c) && c.type === "text" && typeof c.text === "string";
}
function isToolCallBlock(c) {
  return isRecord(c) && c.type === "toolCall" && typeof c.name === "string" && isRecord(c.arguments);
}
var KNOWN_METHODS = new Set(["eesv", "single-pass", "heuristic"]);
var KNOWN_PROFILES = new Set(["light", "balanced", "aggressive"]);
var KNOWN_MODES = new Set(["balanced", "aggressive", "fast", "thorough"]);

// src/utils/file-needles.ts
var GENERIC_BASENAMES = new Set([
  "index.ts",
  "index.js",
  "index.tsx",
  "index.jsx",
  "types.ts",
  "helpers.ts",
  "utils.ts",
  "main.ts",
  "main.js",
  "mod.rs",
  "lib.rs",
  "__init__.py"
]);
var MIN_BARE_BASENAME_LEN = 5;
function normalizePath(filePath) {
  return filePath.replace(/\\/g, "/").replace(/^\.\//, "").toLowerCase();
}
function buildPathNeedles(filePath) {
  const parts = normalizePath(filePath).split("/").filter(Boolean);
  if (parts.length === 0)
    return [];
  const needles = [];
  const basename = parts[parts.length - 1];
  if (!GENERIC_BASENAMES.has(basename) && basename.length >= MIN_BARE_BASENAME_LEN) {
    needles.push(basename);
  }
  for (let j = parts.length - 2;j >= 0; j--) {
    needles.push(parts.slice(j).join("/"));
  }
  return needles;
}
function buildUniquePathNeedles(filePath, allPaths) {
  const normalized = allPaths.map(normalizePath);
  return buildPathNeedles(filePath).filter((needle) => {
    let owners = 0;
    for (const candidate of normalized) {
      if (candidate === needle || candidate.endsWith("/" + needle))
        owners++;
      if (owners > 1)
        return false;
    }
    return owners === 1;
  });
}
function isKnownPathReference(ref, knownPaths) {
  const normalizedRef = normalizePath(ref).replace(/^\/+/, "");
  if (!normalizedRef)
    return false;
  const pathShaped = normalizedRef.includes("/");
  return knownPaths.some((path2) => {
    const normalizedPath = normalizePath(path2).replace(/^\/+/, "");
    if (normalizedPath === normalizedRef || normalizedPath.endsWith("/" + normalizedRef))
      return true;
    if (normalizedPath.endsWith(normalizedRef)) {
      const boundary = normalizedPath[normalizedPath.length - normalizedRef.length - 1];
      if (boundary && !/[\w./-]/.test(boundary))
        return true;
    }
    if (!pathShaped)
      return false;
    return normalizedPath.split("/").some((_, index, parts) => parts.slice(index).join("/").startsWith(normalizedRef + "/"));
  });
}

// src/domain/tool-semantics.ts
var PATH_KEYS = [
  "path",
  "file_path",
  "filePath",
  "filename",
  "file",
  "target_file",
  "file_uri",
  "absolute_path"
];
var PAYLOAD_KEYS = [
  "content",
  "newText",
  "oldText",
  "new_str",
  "old_str",
  "new_string",
  "old_string",
  "edits",
  "patch",
  "replacement"
];
var COMMAND_KEYS = ["command", "cmd", "script"];
function hasPresent(args, keys) {
  return keys.some((k) => args[k] != null);
}
function extractToolPath(args) {
  if (!args || typeof args !== "object")
    return;
  const a = args;
  for (const k of PATH_KEYS) {
    const v = a[k];
    if (typeof v === "string" && v.length > 0)
      return v;
  }
  return;
}
function normalizeToolName(name) {
  if (typeof name !== "string")
    return "";
  return name.replace(/^functions[.:/_-]+/i, "").replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
function nameHas(name, hints) {
  const words = name.split("_");
  return hints.some((hint) => words.includes(hint));
}
function classifyToolOperation(args, toolName) {
  const a = args && typeof args === "object" ? args : {};
  const name = normalizeToolName(toolName);
  const hasPath = extractToolPath(a) !== undefined;
  if (hasPath && hasPresent(a, PAYLOAD_KEYS))
    return "mutate";
  if (hasPresent(a, COMMAND_KEYS))
    return "execute";
  if (hasPath && hasPresent(a, ["text"]) && nameHas(name, ["write", "edit", "patch", "replace", "append", "create", "update", "insert"]))
    return "mutate";
  if (hasPath && nameHas(name, ["delete", "remove", "unlink"]))
    return "delete";
  if (hasPresent(a, ["pattern", "query", "glob"]) || nameHas(name, ["grep", "search", "find", "glob", "rg"]))
    return "search";
  if (nameHas(name, ["list", "ls", "tree"]))
    return "list";
  if (hasPath || nameHas(name, ["read"]))
    return "read";
  return "unknown";
}
// src/utils/file-ref-detect.ts
var CODE_EXT_RE = /\.(ts|tsx|js|jsx|mjs|cjs|rs|py|go|java|rb|cs|cpp|c|h|hpp|swift|kt|scala|php|css|scss|html|json|yaml|yml|toml|md|mdx|sh|sql|tf|ini|env|lock|gradle|xml)$/i;
var VERSION_RE = /^v?\d+(?:\.\d+)+(?:[-+][\w.-]+)?$/i;
var FILE_REF_CANDIDATE_RE = /[\w.\/-]+\.[\w]+/g;
function isLikelyFileRef(candidate) {
  if (candidate.startsWith("//") || VERSION_RE.test(candidate))
    return false;
  if (candidate.includes("/")) {
    const last = candidate.split("/").pop() ?? "";
    return last.length > 0 && !VERSION_RE.test(last);
  }
  return CODE_EXT_RE.test(candidate);
}
function extractFileRefs(summary) {
  const matcher = new RegExp(FILE_REF_CANDIDATE_RE.source, FILE_REF_CANDIDATE_RE.flags);
  const refs = [];
  for (const match of summary.matchAll(matcher)) {
    if (/[\\/]/.test(summary[(match.index ?? 0) + match[0].length] ?? ""))
      continue;
    if (isLikelyFileRef(match[0]))
      refs.push(match[0]);
  }
  return refs;
}

// src/domain/summary-parse.ts
import { createHash } from "crypto";

// src/domain/summary-schema.ts
function classifyHeading(raw) {
  const text = raw.replace(/^#+\s*/, "").replace(/[:\s]+$/, "").trim().toLowerCase();
  if (!text)
    return "unknown";
  if (text === "goal" || text === "goals" || text === "objective" || text === "objectives")
    return "goal";
  if (text.startsWith("constraint") || text.includes("preference"))
    return "constraints";
  if (text === "progress" || text === "status")
    return "progress";
  if (text.includes("key decision") || text === "decisions")
    return "decisions";
  if (text.includes("file") && text.includes("modif"))
    return "files-modified";
  if (text.includes("file") && (text.includes("read") || text.includes("viewed")))
    return "files-read";
  if (text.includes("file") && (text.includes("delet") || text.includes("remov")))
    return "files-deleted";
  if (text.includes("next step") || text === "next actions")
    return "next-steps";
  if (text.includes("critical context") || text === "important context")
    return "critical-context";
  if (text === "topics" || text.includes("topics covered"))
    return "topics";
  if (text.includes("open loop") || text.includes("unresolved"))
    return "open-loops";
  if (text.includes("changes since") || text === "changes")
    return "changes";
  if (text.includes("verification"))
    return "verification-note";
  return "unknown";
}

// src/domain/summary-parse.ts
var HEADING_RE = /^(#{1,3})\s+(.+?)\s*$/;
function summaryEvidenceLine(value, maxLength) {
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, " ").replace(/\s+/g, " ").trim().replace(/^(?:(?:#{1,6}|[-*+]|>)\s+)+/, "").slice(0, maxLength).trim();
}
function summaryPathLine(value) {
  return JSON.stringify(value);
}
function compactPathLine(value, maxLength, digest) {
  const minimal = JSON.stringify("#" + digest);
  if (minimal.length >= maxLength)
    return minimal;
  const chars = Array.from(value.replace(/\\/g, "/"));
  let low = 0;
  let high = chars.length;
  let best = minimal;
  while (low <= high) {
    const length = Math.floor((low + high) / 2);
    const candidate = JSON.stringify("\u2026/" + chars.slice(-length).join("") + "#" + digest);
    if (candidate.length <= maxLength) {
      best = candidate;
      low = length + 1;
    } else {
      high = length - 1;
    }
  }
  return best;
}
function buildSummaryPathEvidence(paths, budgetTokens = PROFILES.balanced.summaryBudgetTokens) {
  const unique = Array.from(new Set(paths.filter(Boolean)));
  if (!unique.length)
    return new Map;
  const full = unique.map((path2) => [path2, summaryPathLine(path2)]);
  const minimumPerLine = JSON.stringify("#" + "x".repeat(12)).length + 3;
  const budgetChars = Math.max(unique.length * minimumPerLine, Math.min(20000, Math.max(4000, Math.floor(budgetTokens * 2))));
  if (full.reduce((total, [, line]) => total + line.length + 3, 0) <= budgetChars) {
    return new Map(full);
  }
  const digests = new Map;
  const owners = new Map;
  for (const path2 of unique) {
    const fullDigest = createHash("sha256").update(path2).digest("base64url");
    let digest = fullDigest.slice(0, 12);
    const owner = owners.get(digest);
    if (owner && owner !== path2) {
      digest = fullDigest;
      digests.set(owner, createHash("sha256").update(owner).digest("base64url"));
    }
    owners.set(digest, path2);
    digests.set(path2, digest);
  }
  const perPath = Math.max(JSON.stringify("#" + "x".repeat(12)).length, Math.floor((budgetChars - unique.length * 3) / unique.length));
  return new Map(unique.map((path2) => [
    path2,
    compactPathLine(path2, perPath, digests.get(path2) ?? "")
  ]));
}
function mergeBodies(first, second) {
  const seen = new Set;
  return [first, second].filter(Boolean).flatMap((body) => body.split(`
`)).filter((line) => seen.has(line) ? false : (seen.add(line), true)).join(`
`).trim();
}
function parseSummary(markdown) {
  const sections = [];
  const lines = markdown.split(`
`);
  let currentHeading = "";
  let currentKind = "unknown";
  let bodyLines = [];
  let fence = null;
  let started = false;
  const flush = () => {
    if (!started)
      return;
    const body = bodyLines.join(`
`).trim();
    const existing = currentKind === "unknown" ? undefined : sections.find((s) => s.kind === currentKind);
    if (existing)
      existing.body = mergeBodies(existing.body, body);
    else
      sections.push({
        kind: currentKind,
        heading: currentHeading.trim(),
        body
      });
  };
  for (const line of lines) {
    const fenceMatch = line.match(/^\s{0,3}(`{3,}|~{3,})(.*)$/);
    if (fenceMatch) {
      const marker = fenceMatch[1][0];
      const markerLength = fenceMatch[1].length;
      if (!fence) {
        fence = { marker, length: markerLength };
      } else if (marker === fence.marker && markerLength >= fence.length && !fenceMatch[2].trim()) {
        fence = null;
      }
      if (started)
        bodyLines.push(line);
      continue;
    }
    if (!fence) {
      const heading = line.match(HEADING_RE);
      if (heading) {
        const kind = classifyHeading(heading[2]);
        if (heading[1].length <= 2 || kind !== "unknown") {
          flush();
          currentHeading = "## " + heading[2].trim();
          currentKind = kind;
          bodyLines = [];
          started = true;
          continue;
        }
      }
    }
    if (started)
      bodyLines.push(line);
  }
  flush();
  return { sections };
}
function findSection(summary, kind) {
  const parsed = typeof summary === "string" ? parseSummary(summary) : summary;
  return parsed.sections.find((s) => s.kind === kind);
}

// src/utils/extraction.ts
function nestedToolCallId(wrapperId, messageIndex, toolIndex, nestedId) {
  return typeof nestedId === "string" ? nestedId : wrapperId ? wrapperId + "_" + toolIndex : ID_PREFIX.MULTI_TOOL_USE_SYNTHETIC + messageIndex + "_" + toolIndex;
}
function flattenToolCallBlock(b) {
  if (!isToolCallBlock(b))
    return [];
  if (b.name === "multi_tool_use.parallel" && Array.isArray(b.arguments?.tool_uses)) {
    return b.arguments.tool_uses.map((u) => {
      const recipient = u?.recipient_name ?? "";
      return {
        name: recipient.replace(/^functions\./, ""),
        id: u?.id ?? undefined,
        arguments: u?.parameters ?? {}
      };
    });
  }
  return [{ name: b.name, id: b.id, arguments: b.arguments }];
}
function extractText(content) {
  if (typeof content === "string")
    return content;
  if (!Array.isArray(content))
    return "";
  return content.map((b) => {
    if (typeof b === "string")
      return b;
    if (isTextBlock(b))
      return b.text;
    return "";
  }).join("");
}
function buildToolCallIndex(msgs) {
  const idx = new Map;
  for (let i = 0;i < msgs.length; i++) {
    const m = msgs[i];
    if (m.role !== "assistant")
      continue;
    const blocks = Array.isArray(m.content) ? m.content : [];
    for (const b of blocks) {
      if (!isToolCallBlock(b))
        continue;
      if (b.id) {
        idx.set(b.id, { name: b.name, arguments: b.arguments, msgIndex: i });
      }
      if (b.name === "multi_tool_use.parallel" && Array.isArray(b.arguments?.tool_uses)) {
        const nested = flattenToolCallBlock(b);
        for (let t = 0;t < nested.length; t++) {
          const tool = nested[t];
          const id = nestedToolCallId(b.id, i, t, tool.id);
          idx.set(id, {
            name: tool.name,
            arguments: tool.arguments,
            msgIndex: i
          });
        }
      }
    }
  }
  return idx;
}
var CONSTRAINT_PATTERNS = [
  {
    re: /\b(?:must|need|require|has to|important)\b.*\b(?:be|use|have|include|support)\b/i,
    cat: "requirement",
    conf: TUNING.CONFIDENCE_HIGH
  },
  {
    re: /\b(?:don't|never|avoid|shouldn't|must not|do not|no\s+(?:need|want))\b/i,
    cat: "prohibition",
    conf: TUNING.CONFIDENCE_MEDIUM
  },
  {
    re: /\b(?:prefer|like|want|would rather|should)\b.*\b(?:use|be|have|with)\b/i,
    cat: "preference",
    conf: TUNING.CONFIDENCE_LOW
  },
  {
    re: /(?<![A-Za-z0-9_])(?:yapma|kullanma|sak\u0131n|sak\u0131nha|asla(?:\s+(?:kullanma|yapma|getirme))?|bunu yapma)(?![A-Za-z0-9_])/iu,
    cat: "prohibition",
    conf: TUNING.CONFIDENCE_MEDIUM
  },
  {
    re: /(?<![A-Za-z0-9_])(?:kritik|kritikal|\u00F6nemli|onemli|\u015Fart|sart|zorunlu|\u015Fart ko\u015Ful|\u00F6nemli \u015Fart|kesinlikle|kesinlikle \u015Fart|b\u00F6yle olsun|b\u00F6yle yap\u0131n|\u015F\u00F6yle olsun|\u015F\u00F6yle yap\u0131n)(?![A-Za-z0-9_])/iu,
    cat: "requirement",
    conf: TUNING.CONFIDENCE_MEDIUM
  },
  {
    re: /(?<![A-Za-z0-9_])(?:tercih|isterim|olsun|kullanal\u0131m|yapal\u0131m|istiyorum)(?![A-Za-z0-9_])/iu,
    cat: "preference",
    conf: TUNING.CONFIDENCE_LOW
  }
];
function isDiagnosticConstraintText(text) {
  const candidate = text.replace(/^\s*[-*]\s+/, "").trim();
  return /^(?:\[[^\]]+\]\s*)?(?:npm\s+(?:error|warn|notice|audit|verbose|info)\b|(?:rg|grep):|command exited\b)/i.test(candidate);
}

// src/infra/clock.ts
var systemClock = {
  now: () => Date.now()
};

// src/infra/llm-client.ts
var _complete = null;
var _completeSimple = null;
var _stream = null;
var _streamSimple = null;
async function resolveComplete() {
  if (_complete)
    return _complete;
  const mod = await import("@earendil-works/pi-ai/compat");
  const fn = mod.complete;
  if (typeof fn !== "function")
    throw new Error("smart-compact: pi-ai /compat did not export complete()");
  _complete = fn;
  return fn;
}
async function resolveCompleteSimple() {
  if (_completeSimple)
    return _completeSimple;
  const mod = await import("@earendil-works/pi-ai/compat");
  const fn = mod.completeSimple;
  if (typeof fn !== "function")
    throw new Error("smart-compact: pi-ai /compat did not export completeSimple()");
  _completeSimple = fn;
  return fn;
}
async function resolveStream() {
  if (_stream)
    return _stream;
  const mod = await import("@earendil-works/pi-ai/compat");
  if (typeof mod.stream !== "function")
    throw new Error("smart-compact: pi-ai /compat did not export stream()");
  _stream = mod.stream;
  return _stream;
}
async function resolveStreamSimple() {
  if (_streamSimple)
    return _streamSimple;
  const mod = await import("@earendil-works/pi-ai/compat");
  if (typeof mod.streamSimple !== "function")
    throw new Error("smart-compact: pi-ai /compat did not export streamSimple()");
  _streamSimple = mod.streamSimple;
  return _streamSimple;
}
function isChatGptCodex(model) {
  if (model.api !== "openai-codex-responses")
    return false;
  return !model.baseUrl || model.baseUrl.includes("chatgpt.com");
}
function withCodexWireLimit(model, opts) {
  if (model.api !== "openai-codex-responses" || isChatGptCodex(model) || !opts.maxTokens)
    return opts;
  const previous = opts.onPayload;
  return {
    ...opts,
    onPayload: async (payload, requestModel) => {
      const transformed = await previous?.(payload, requestModel);
      const body = transformed ?? payload;
      return body && typeof body === "object" ? {
        ...body,
        max_output_tokens: opts.maxTokens
      } : body;
    }
  };
}
function resolveCodexWatchdogMs(maxTokens, configuredMs = 0) {
  if (configuredMs > 0)
    return configuredMs;
  return Math.min(90000, Math.max(15000, 1e4 + (maxTokens ?? 4096) * 8));
}
function streamedChars(event) {
  if (event.type === "text_delta" || event.type === "thinking_delta" || event.type === "toolcall_delta") {
    return event.delta.length;
  }
  return 0;
}
function assertSuccessful(message) {
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    throw new Error(message.errorMessage || "LLM request failed");
  }
  return message;
}
function resolveProviderWatchdogMs(provider, maxTokens, configuredMs = 0) {
  const multiplier = provider && configuredMs <= 0 ? getProviderCaps(provider).timeoutMultiplier : 1;
  return Math.round(resolveCodexWatchdogMs(maxTokens, configuredMs) * multiplier);
}
async function withProviderDeadline(opts, invoke, provider) {
  if (opts.signal?.aborted)
    throw new Error("LLM request aborted before dispatch");
  const controller = new AbortController;
  const watchdogMs = resolveProviderWatchdogMs(provider, opts.maxTokens, opts.codexWatchdogMs);
  const abort = Promise.withResolvers();
  const abortFromCaller = () => {
    controller.abort(opts.signal?.reason);
    abort.reject(new Error("LLM request aborted by caller"));
  };
  opts.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = Promise.withResolvers();
  const timer = setTimeout(() => {
    controller.abort("provider-watchdog");
    timeout.reject(new Error("Provider watchdog stopped generation after " + watchdogMs + "ms"));
  }, watchdogMs);
  if (typeof timer === "object" && "unref" in timer)
    timer.unref();
  try {
    return await Promise.race([
      invoke({ ...opts, signal: controller.signal }),
      abort.promise,
      timeout.promise
    ]);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", abortFromCaller);
  }
}
async function completeChatGptCodex(model, body, opts) {
  const controller = new AbortController;
  const watchdogMs = resolveCodexWatchdogMs(opts.maxTokens, opts.codexWatchdogMs);
  let watchdogReason = null;
  let visibleChars = 0;
  const abortFromCaller = () => controller.abort(opts.signal?.reason);
  opts.signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (opts.signal?.aborted)
    abortFromCaller();
  const timer = setTimeout(() => {
    watchdogReason = "time";
    controller.abort("codex-watchdog");
  }, watchdogMs);
  timer.unref?.();
  try {
    const limited = { ...opts, signal: controller.signal };
    const events = opts.reasoning === undefined ? (await resolveStream())(model, body, limited) : (await resolveStreamSimple())(model, body, limited);
    let final;
    for await (const event of events) {
      visibleChars += streamedChars(event);
      if (!watchdogReason && opts.maxTokens && visibleChars > opts.maxTokens * 3) {
        watchdogReason = "visible-output";
        controller.abort("codex-visible-output-cap");
      }
      if (event.type === "done")
        final = event.message;
      else if (event.type === "error")
        final = event.error;
    }
    if (watchdogReason) {
      throw new Error("Codex " + watchdogReason + " watchdog stopped generation after " + watchdogMs + "ms / " + visibleChars + " streamed chars");
    }
    if (!final)
      throw new Error("Codex stream ended without a final message");
    return assertSuccessful(final);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", abortFromCaller);
  }
}
var rawLlmClient = {
  complete: async (model, body, originalOpts) => {
    const opts = withCodexWireLimit(model, originalOpts);
    return withProviderDeadline(opts, async (bounded) => {
      if (isChatGptCodex(model))
        return completeChatGptCodex(model, body, bounded);
      const response = bounded.reasoning === undefined ? await (await resolveComplete())(model, body, bounded) : await (await resolveCompleteSimple())(model, body, bounded);
      return assertSuccessful(response);
    }, model.provider);
  }
};
var defaultLlmClient = rawLlmClient;
var _client = defaultLlmClient;
function getLlmClient() {
  return _client;
}

// src/infra/services.ts
import crypto from "crypto";

// src/domain/scrub.ts
var SECRET_PATTERNS = [
  {
    kind: "private-key",
    regex: /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g
  },
  { kind: "aws-access-key", regex: /\bAKIA[0-9A-Z]{16}\b/g },
  { kind: "google-api-key", regex: /\bAIza[0-9A-Za-z_-]{30,}\b/g },
  { kind: "stripe-key", regex: /\b[rs]k_(?:live|test)_[0-9A-Za-z]{16,}\b/g },
  { kind: "gitlab-token", regex: /\bglpat-[0-9A-Za-z_-]{20,}\b/g },
  { kind: "npm-token", regex: /\bnpm_[0-9A-Za-z]{30,}\b/g },
  { kind: "github-token", regex: /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g },
  { kind: "api-key", regex: /\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b/g },
  { kind: "slack-token", regex: /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g },
  {
    kind: "jwt",
    regex: /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g
  },
  {
    kind: "bearer-token",
    regex: /\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*/gi,
    replacement: () => "Bearer [REDACTED:bearer-token]"
  },
  {
    kind: "connection-password",
    regex: /\b([a-z][a-z0-9+.-]*:\/\/[^:\s/@]+:)[^@\s/]+(@)/gi,
    replacement: (prefix, suffix) => prefix + "[REDACTED:password]" + suffix
  },
  {
    kind: "credential",
    regex: /\b((?:[A-Za-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|password|passwd|secret(?:[_-]?(?:access)?[_-]?key)?|client[_-]?secret)(?:[_-][A-Za-z0-9]+)*)\s*([:=])\s*["']?([^\s"']{16,})["']?/gi,
    replacement: (name, separator, value, match) => /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+$/.test(value) ? match : name + separator + "[REDACTED:credential]"
  }
];
function passesLuhn(candidate) {
  const digits = candidate.replace(/\D/g, "");
  if (digits.length < 13 || digits.length > 19)
    return false;
  if (/^(\d)\1+$/.test(digits))
    return false;
  let sum = 0, double = false;
  for (let i = digits.length - 1;i >= 0; i--) {
    let d = digits.charCodeAt(i) - 48;
    if (double) {
      d *= 2;
      if (d > 9)
        d -= 9;
    }
    sum += d;
    double = !double;
  }
  return sum % 10 === 0;
}
var PII_PATTERNS = [
  { kind: "email", regex: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi },
  {
    kind: "payment-card",
    regex: /\b(?:\d[ -]*?){13,19}\b/g,
    replacement: (candidate) => passesLuhn(candidate) ? "[REDACTED:payment-card]" : candidate
  },
  { kind: "phone", regex: /(?<![\w.])(?:\+?\d[\d ()-]{8,}\d)(?![\w.])/g }
];
function redact(text, patterns) {
  const counts = new Map;
  let value = text;
  for (const pattern of patterns) {
    value = value.replace(pattern.regex, (...args) => {
      const match = String(args[0]);
      let replacement = "[REDACTED:" + pattern.kind + "]";
      if (pattern.replacement) {
        const groups = args.slice(1, -2).map(String);
        replacement = pattern.replacement(...groups, match);
      }
      if (replacement === match)
        return match;
      counts.set(pattern.kind, (counts.get(pattern.kind) ?? 0) + 1);
      return replacement;
    });
  }
  return {
    value,
    findings: [...counts].map(([kind, count]) => ({ kind, count }))
  };
}
function mergeFindings(target, findings) {
  for (const finding of findings)
    target.set(finding.kind, (target.get(finding.kind) ?? 0) + finding.count);
}
var SECRET_KEY_NAMES = {
  api_key: true,
  apikey: true,
  access_token: true,
  auth_token: true,
  authorization: true,
  password: true,
  passwd: true,
  secret: true,
  secret_key: true,
  secret_access_key: true,
  client_secret: true,
  private_key: true,
  database_url: true,
  connection_string: true,
  token: true,
  refresh_token: true,
  session_token: true,
  credential: true,
  credentials: true,
  cookie: true,
  set_cookie: true,
  otp: true,
  one_time_password: true,
  passcode: true
};
function normalizeObjectKey(key) {
  return key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
function isSecretBearingKey(key) {
  const normalized = normalizeObjectKey(key);
  if (SECRET_KEY_NAMES[normalized])
    return true;
  return /(?:^|_)(?:api_key|access_token|auth_token|password|passwd|secret_access_key|client_secret|private_key|refresh_token|session_token|one_time_password|passcode)(?:_|$)/.test(normalized);
}

class SecretScrubber {
  secretsEnabled;
  piiEnabled;
  total = 0;
  constructor(secretsEnabled = true, piiEnabled = false) {
    this.secretsEnabled = secretsEnabled;
    this.piiEnabled = piiEnabled;
  }
  scrubText(text) {
    let value = text;
    const findings = new Map;
    if (this.secretsEnabled) {
      const result = redact(value, SECRET_PATTERNS);
      value = result.value;
      mergeFindings(findings, result.findings);
    }
    if (this.piiEnabled) {
      const result = redact(value, PII_PATTERNS);
      value = result.value;
      mergeFindings(findings, result.findings);
    }
    const merged = [...findings].map(([kind, count]) => ({ kind, count }));
    this.total += merged.reduce((sum, finding) => sum + finding.count, 0);
    return { value, findings: merged };
  }
  scrubValue(input) {
    const findings = new Map;
    const seen = new WeakMap;
    const recordCredential = () => {
      findings.set("credential", (findings.get("credential") ?? 0) + 1);
      this.total++;
    };
    const visit = (value2) => {
      if (typeof value2 === "string") {
        const result = this.scrubText(value2);
        mergeFindings(findings, result.findings);
        return result.value;
      }
      if (value2 == null || typeof value2 !== "object")
        return value2;
      const cached = seen.get(value2);
      if (cached !== undefined)
        return cached;
      if (Array.isArray(value2)) {
        const output2 = [];
        seen.set(value2, output2);
        for (const item of value2)
          output2.push(visit(item));
        return output2;
      }
      const output = {};
      seen.set(value2, output);
      for (const [key, item] of Object.entries(value2)) {
        const carriesSecret = typeof item === "string" && item.length >= 8;
        if (this.secretsEnabled && isSecretBearingKey(key) && carriesSecret) {
          output[key] = "[REDACTED:credential]";
          recordCredential();
        } else {
          output[key] = visit(item);
        }
      }
      return output;
    };
    const value = visit(input);
    return {
      value,
      findings: [...findings].map(([kind, count]) => ({ kind, count }))
    };
  }
  count() {
    return this.total;
  }
}

// src/infra/services.ts
class ToolSupportCache {
  ttlMs;
  maxEntries;
  entries = new Map;
  constructor(ttlMs = ONE_HOUR_MS, maxEntries = 128) {
    this.ttlMs = ttlMs;
    this.maxEntries = maxEntries;
  }
  get(key, now) {
    const entry = this.entries.get(key);
    if (!entry)
      return;
    if (now - entry.timestamp > this.ttlMs) {
      this.entries.delete(key);
      return;
    }
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.result;
  }
  set(key, value, now) {
    this.entries.delete(key);
    this.entries.set(key, { result: value, timestamp: now });
    while (this.entries.size > Math.max(1, this.maxEntries)) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined)
        break;
      this.entries.delete(oldest);
    }
  }
  clear() {
    this.entries.clear();
  }
  size() {
    return this.entries.size;
  }
}

class MetricsSink {
  buf = [];
  maxEntries;
  constructor(maxEntries = METRICS_BUFFER_MAX) {
    this.maxEntries = maxEntries;
  }
  record(metric) {
    this.buf.push(metric);
    if (this.buf.length > this.maxEntries) {
      this.buf.splice(0, this.buf.length - Math.floor(this.maxEntries / 2));
    }
  }
  snapshot() {
    return [...this.buf];
  }
  clear() {
    this.buf.length = 0;
  }
  summary() {
    const n = this.buf.length;
    if (!n)
      return { totalCalls: 0, totalInput: 0, totalOutput: 0, totalCacheHit: 0, totalCacheWrite: 0, avgLatency: 0, cacheHitRate: 0 };
    let totalInput = 0, totalOutput = 0, totalCacheHit = 0, totalCacheWrite = 0, totalLatency = 0;
    for (const m of this.buf) {
      totalInput += m.inputTokens;
      totalOutput += m.outputTokens;
      totalCacheHit += m.cacheHitTokens;
      totalCacheWrite += m.cacheWriteTokens ?? 0;
      totalLatency += m.latencyMs;
    }
    const promptInput = totalInput + totalCacheHit + totalCacheWrite;
    const cacheHitRate = promptInput > 0 ? totalCacheHit / promptInput : 0;
    return {
      totalCalls: n,
      totalInput,
      totalOutput,
      totalCacheHit,
      totalCacheWrite,
      avgLatency: Math.round(totalLatency / n),
      cacheHitRate
    };
  }
}

class BudgetExceededError extends Error {
  reason;
  constructor(reason) {
    super("Smart Compact " + reason + " budget exhausted");
    this.reason = reason;
    this.name = "BudgetExceededError";
  }
}

class BudgetGuard {
  maxCalls;
  maxLatencyMs;
  clock;
  maxInputTokens;
  maxOutputTokens;
  calls = 0;
  inputTokens = 0;
  outputTokens = 0;
  reservedOutputTokens = 0;
  startedAt;
  lastReason = null;
  constructor(maxCalls = 0, maxLatencyMs = 0, clock = systemClock, maxInputTokens = 0, maxOutputTokens = 0) {
    this.maxCalls = maxCalls;
    this.maxLatencyMs = maxLatencyMs;
    this.clock = clock;
    this.maxInputTokens = maxInputTokens;
    this.maxOutputTokens = maxOutputTokens;
    this.startedAt = clock.now();
  }
  reserveCall(estimatedInputTokens = 0, expectedOutputTokens = 0) {
    if (this.maxLatencyMs > 0 && this.clock.now() - this.startedAt >= this.maxLatencyMs) {
      this.lastReason = "latency";
      throw new BudgetExceededError("latency");
    }
    if (this.maxCalls > 0 && this.calls >= this.maxCalls) {
      this.lastReason = "calls";
      throw new BudgetExceededError("calls");
    }
    const outputReservation = Math.max(0, expectedOutputTokens);
    if (this.maxInputTokens > 0 && this.inputTokens + estimatedInputTokens > this.maxInputTokens || this.maxOutputTokens > 0 && (this.outputTokens + this.reservedOutputTokens >= this.maxOutputTokens || this.outputTokens + this.reservedOutputTokens + outputReservation > this.maxOutputTokens)) {
      this.lastReason = "tokens";
      throw new BudgetExceededError("tokens");
    }
    this.calls++;
    this.inputTokens += estimatedInputTokens;
    this.reservedOutputTokens += outputReservation;
    return outputReservation;
  }
  reconcileInput(estimated, actual) {
    this.inputTokens = Math.max(0, this.inputTokens - estimated + actual);
    if (this.maxInputTokens > 0 && this.inputTokens >= this.maxInputTokens)
      this.lastReason = "tokens";
  }
  reconcileOutput(reserved, actual) {
    this.reservedOutputTokens = Math.max(0, this.reservedOutputTokens - Math.max(0, reserved));
    this.outputTokens += Math.max(0, actual);
    if (this.maxOutputTokens > 0 && this.outputTokens + this.reservedOutputTokens >= this.maxOutputTokens)
      this.lastReason = "tokens";
  }
  commitFailedOutput(reserved) {
    const amount = Math.max(0, reserved);
    this.reservedOutputTokens = Math.max(0, this.reservedOutputTokens - amount);
    this.outputTokens += amount;
    if (this.maxOutputTokens > 0 && this.outputTokens >= this.maxOutputTokens)
      this.lastReason = "tokens";
  }
  recordOutput(actual) {
    this.reconcileOutput(0, actual);
  }
  setLimits(maxCalls, maxInputTokens, maxOutputTokens = 0) {
    this.maxCalls = maxCalls;
    this.maxInputTokens = maxInputTokens;
    this.maxOutputTokens = maxOutputTokens;
  }
  callCount() {
    return this.calls;
  }
  remainingCalls() {
    return this.maxCalls > 0 ? Math.max(0, this.maxCalls - this.calls) : Number.POSITIVE_INFINITY;
  }
  inputTokenCount() {
    return this.inputTokens;
  }
  outputTokenCount() {
    return this.outputTokens;
  }
  remainingOutputTokens() {
    return this.maxOutputTokens > 0 ? Math.max(0, this.maxOutputTokens - this.outputTokens - this.reservedOutputTokens) : Number.POSITIVE_INFINITY;
  }
  reason() {
    return this.lastReason;
  }
}

class ExtractionCacheStats {
  hits = 0;
  misses = 0;
  recordHit() {
    this.hits++;
  }
  recordMiss() {
    this.misses++;
  }
  snapshot() {
    const total = this.hits + this.misses;
    return { hits: this.hits, misses: this.misses, hitRate: total > 0 ? this.hits / total : 0 };
  }
  clear() {
    this.hits = 0;
    this.misses = 0;
  }
}
function makeCompactSessionId() {
  return "sc-" + Date.now().toString(36) + "-" + crypto.randomBytes(4).toString("hex");
}
function createServices(overrides = {}) {
  return {
    clock: overrides.clock ?? systemClock,
    llm: overrides.llm ?? { complete: (...args) => getLlmClient().complete(...args) },
    toolSupport: overrides.toolSupport ?? new ToolSupportCache,
    metrics: overrides.metrics ?? new MetricsSink,
    extractionCacheStats: overrides.extractionCacheStats ?? new ExtractionCacheStats,
    tokenCalibration: overrides.tokenCalibration ?? new TokenCalibrationStore,
    budget: overrides.budget ?? new BudgetGuard,
    scrubber: overrides.scrubber ?? new SecretScrubber,
    thinkingLevels: overrides.thinkingLevels ?? {
      summaryThinkingLevel: DEFAULT_CONFIG.summaryThinkingLevel,
      segmentationThinkingLevel: DEFAULT_CONFIG.segmentationThinkingLevel
    },
    codexWatchdogMs: overrides.codexWatchdogMs ?? DEFAULT_CONFIG.codexMaxCallMs,
    compactSessionId: overrides.compactSessionId ?? makeCompactSessionId()
  };
}
var processToolSupport = new ToolSupportCache;
var processTokenCalibration = new TokenCalibrationStore;
var _default = createServices();

// src/utils/cache.ts
var INTERNAL_PHASES = new Set([
  "explore-retry",
  "explore-direct",
  "single-pass",
  "batch",
  "assemble",
  "patch"
]);
var SEGMENTATION_PHASES = new Set([
  "probe",
  "explore",
  "explore-loop",
  "explore-retry",
  "explore-direct"
]);
function readMetricsLog(limit = 100) {
  try {
    const logPath = metricsLogFile();
    if (!fs2.existsSync(logPath))
      return [];
    const stat = fs2.statSync(logPath);
    const TAIL_CHUNK = 64 * 1024;
    const wantBytes = Math.min(stat.size, Math.max(TAIL_CHUNK, limit * 8 * 512));
    const startPos = Math.max(0, stat.size - wantBytes);
    const fd = fs2.openSync(logPath, "r");
    try {
      const buf = Buffer.alloc(wantBytes);
      const bytesRead = fs2.readSync(fd, buf, 0, wantBytes, startPos);
      let text = buf.subarray(0, bytesRead).toString("utf8");
      if (startPos > 0) {
        const nl = text.indexOf(`
`);
        if (nl >= 0)
          text = text.slice(nl + 1);
      }
      const lines = text.split(`
`).filter(Boolean);
      const entries = [];
      for (const line of lines) {
        try {
          entries.push(JSON.parse(line));
        } catch {
          warn("Skipping corrupt compact metrics line");
        }
      }
      return entries.slice(-limit);
    } finally {
      fs2.closeSync(fd);
    }
  } catch (e) {
    warn("readMetricsLog failed", e);
    return [];
  }
}

// scripts/telemetry-report.ts
var minArg = process.argv.find((arg) => arg.startsWith("--min-canary-runs="));
var minCanaryRuns = minArg ? Number(minArg.split("=")[1]) : 20;
if (!Number.isInteger(minCanaryRuns) || minCanaryRuns < 5) {
  console.error("--min-canary-runs must be an integer >= 5");
  process.exit(1);
}
var report = buildPrivacySafeTelemetry(readMetricsLog(1e4), readJsonlTail(damageReportsFile(), 1e4), { version: VERSION, minCanaryRuns });
console.log(process.argv.includes("--json") ? JSON.stringify(report, null, 2) : formatPrivacySafeTelemetry(report));
