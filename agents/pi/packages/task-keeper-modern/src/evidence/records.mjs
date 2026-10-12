export const evidenceReasonCodes = [
    "verified",
    "nonzero_exit",
    "required_tests_not_passed",
    "required_test_ids_not_passed",
    "semantic_assertion_failed",
    "spawn_failed",
    "cancelled",
    "timeout",
    "supervisor_failed",
    "unfinished_descendants_terminated",
    "external_processes_not_confirmed_stopped",
    "command_terminal_not_observed",
    "output_truncated",
    "test_count_unknown",
    "json_result_invalid",
    "test_results_invalid",
    "required_test_ids_invalid",
    "not_sent",
    "execution_unknown",
    "oracle_passed",
    "oracle_failed"
];
export const evidenceUnknownCodes = [
    "PROCESS_IDENTITY_UNOBSERVED",
    "TERMINATION_UNKNOWN",
    "TERMINAL_UNOBSERVED",
    "EXIT_CODE_UNKNOWN",
    "TEST_COUNTS_UNKNOWN",
    "OUTPUT_TRUNCATED",
    "PROTOCOL_UNKNOWN",
    "START_TIME_UNKNOWN",
    "END_TIME_UNKNOWN"
];
const originKeys = [
    "profileId",
    "runtimeIdentity",
    "configDigest",
    "platform",
    "architecture",
    "snapshot",
    "inputSnapshotDigest",
    "specVersion",
    "policyDigest",
    "bindingDigest",
    "environmentDigest",
    "contractDigest",
    "cwdIdentity",
    "entryIdentity",
    "argvDigest"
];
const hashKeys = [
    "runtimeIdentity",
    "configDigest",
    "inputSnapshotDigest",
    "policyDigest",
    "bindingDigest",
    "environmentDigest",
    "contractDigest",
    "cwdIdentity",
    "entryIdentity",
    "argvDigest"
];
const id = (value)=>typeof value === "string" && /^[a-zA-Z0-9_.:-]{1,200}$/.test(value) && ![
        ".",
        ".."
    ].includes(value);
const hash = (value)=>typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const integer = (value)=>typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const nullableInteger = (value)=>value === null || integer(value);
function requireFact(ok) {
    if (!ok) throw new Error("INVALID_EVIDENCE_RECORD");
}
function closed(value, keys) {
    requireFact(value !== null && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype);
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const actual = Reflect.ownKeys(descriptors);
    requireFact(actual.length === keys.length && actual.every((key)=>typeof key === "string" && keys.includes(key)));
    for (const key of keys)requireFact(descriptors[key] && "value" in descriptors[key] && descriptors[key].enumerable);
    return Object.fromEntries(keys.map((key)=>[
            key,
            descriptors[key].value
        ]));
}
function unknownList(value) {
    requireFact(Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype);
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const length = descriptors.length.value;
    requireFact(length <= evidenceUnknownCodes.length && Reflect.ownKeys(descriptors).length === length + 1);
    const result = [];
    for(let index = 0; index < length; index++){
        const item = descriptors[String(index)];
        requireFact(item && "value" in item && item.enumerable && evidenceUnknownCodes.includes(item.value));
        result.push(item.value);
    }
    requireFact(new Set(result).size === result.length);
    return Object.freeze(result);
}
function origin(value) {
    const fields = closed(value, originKeys);
    for (const key of hashKeys)requireFact(hash(fields[key]));
    for (const key of [
        "profileId",
        "platform",
        "architecture",
        "snapshot"
    ])requireFact(id(fields[key]));
    requireFact(integer(fields.specVersion) && fields.specVersion > 0);
    return Object.freeze(fields);
}
export function createEvidenceRecord(value) {
    const record = closed(value, [
        "schemaVersion",
        "jobId",
        "attemptId",
        "checkId",
        "layer",
        "origin",
        "execution",
        "result",
        "artifact"
    ]);
    requireFact(record.schemaVersion === 1 && [
        record.jobId,
        record.attemptId,
        record.checkId
    ].every(id));
    requireFact([
        "checker",
        "reviewer",
        "worker",
        "terminal"
    ].includes(record.layer));
    record.origin = origin(record.origin);
    const execution = closed(record.execution, [
        "startedAt",
        "endedAt",
        "protocolStatus",
        "exitCode",
        "counts",
        "terminalObserved",
        "termination",
        "processIdentity",
        "notSent",
        "unknowns"
    ]);
    requireFact(nullableInteger(execution.startedAt) && nullableInteger(execution.endedAt));
    requireFact(execution.startedAt === null || execution.endedAt === null || execution.endedAt >= execution.startedAt);
    requireFact([
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "unknown",
        "not_sent"
    ].includes(execution.protocolStatus));
    requireFact(execution.exitCode === null || Number.isSafeInteger(execution.exitCode));
    requireFact([
        true,
        false,
        null
    ].includes(execution.terminalObserved) && [
        "confirmed",
        "unknown"
    ].includes(execution.termination));
    requireFact(typeof execution.notSent === "boolean" && (execution.processIdentity === null || hash(execution.processIdentity)));
    execution.unknowns = unknownList(execution.unknowns);
    if (execution.counts !== null) {
        const counts = closed(execution.counts, [
            "tests",
            "passed",
            "failed",
            "skipped"
        ]);
        requireFact(Object.values(counts).every(integer) && counts.passed + counts.failed + counts.skipped === counts.tests);
        execution.counts = Object.freeze(counts);
    }
    const result = closed(record.result, [
        "status",
        "reason"
    ]);
    requireFact([
        "passed",
        "failed",
        "unknown",
        "not_run"
    ].includes(result.status) && evidenceReasonCodes.includes(result.reason));
    requireFact(result.status !== "passed" || [
        "verified",
        "oracle_passed"
    ].includes(result.reason));
    requireFact(result.status !== "not_run" || result.reason === "not_sent");
    if (execution.notSent) {
        requireFact(execution.protocolStatus === "not_sent" && execution.startedAt === null && execution.endedAt === null && execution.processIdentity === null && execution.exitCode === null && execution.counts === null && execution.terminalObserved !== true && [
            "not_run",
            "unknown"
        ].includes(result.status));
    } else {
        requireFact(execution.protocolStatus !== "not_sent" && result.status !== "not_run");
        if (execution.processIdentity === null) requireFact(result.status !== "passed" && execution.unknowns.includes("PROCESS_IDENTITY_UNOBSERVED"));
    }
    record.execution = Object.freeze(execution);
    record.result = Object.freeze(result);
    if (record.artifact !== null) {
        const artifact = closed(record.artifact, [
            "id",
            "source",
            "digest",
            "bytes"
        ]);
        requireFact(id(artifact.id) && [
            "verifier",
            "reviewer",
            "runtime"
        ].includes(artifact.source) && hash(artifact.digest) && integer(artifact.bytes));
        record.artifact = Object.freeze(artifact);
    }
    requireFact(new TextEncoder().encode(JSON.stringify(record)).byteLength <= 1024 * 1024);
    return Object.freeze(record);
}
function view(record, validity, result, reasons, supportsPassed = false) {
    return Object.freeze({
        record,
        validity,
        result,
        counts: record?.execution.counts ?? null,
        reasons: Object.freeze(reasons),
        supportsPassed
    });
}
export function reduceEvidence(value, current, verifiedArtifactFact) {
    let record;
    try {
        record = createEvidenceRecord(value);
    } catch  {
        return view(null, "invalid", "unknown", [
            "record_invalid"
        ]);
    }
    const execution = record.execution, counts = execution.counts;
    const failedFact = !execution.notSent && (execution.exitCode !== null && execution.exitCode !== 0 || counts !== null && (counts.tests === 0 || counts.passed === 0 || counts.failed > 0) || [
        "failed",
        "cancelled",
        "timed_out"
    ].includes(execution.protocolStatus));
    const unknownFact = execution.termination === "unknown" || execution.terminalObserved !== true || execution.protocolStatus === "unknown" || execution.exitCode === null || execution.startedAt === null || execution.endedAt === null || execution.unknowns.length > 0;
    const result = record.result.status === "failed" || failedFact ? "failed" : execution.notSent ? record.result.status : unknownFact ? "unknown" : record.result.status;
    const artifact = record.artifact;
    try {
        if (!artifact) requireFact(execution.notSent);
        else {
            const fact = closed(verifiedArtifactFact, [
                "readable",
                "id",
                "jobId",
                "snapshot",
                "source",
                "digest",
                "bytes"
            ]);
            requireFact(fact.readable === true && fact.id === artifact.id && fact.jobId === record.jobId && fact.snapshot === record.origin.snapshot && fact.source === artifact.source && fact.digest === artifact.digest && fact.bytes === artifact.bytes);
            const sources = record.layer === "checker" ? [
                "verifier"
            ] : record.layer === "reviewer" ? [
                "reviewer",
                "verifier"
            ] : [
                "runtime"
            ];
            requireFact(sources.includes(artifact.source));
        }
    } catch  {
        return view(record, "invalid", result, [
            "artifact_invalid"
        ]);
    }
    let context, currentOrigin;
    try {
        context = closed(current, [
            "jobId",
            "attemptId",
            "checkId",
            "origin",
            "requiredLayer",
            "oraclePassed"
        ]);
        requireFact([
            context.jobId,
            context.attemptId,
            context.checkId
        ].every(id) && [
            "checker",
            "reviewer"
        ].includes(context.requiredLayer) && typeof context.oraclePassed === "boolean");
        currentOrigin = origin(context.origin);
    } catch  {
        return view(record, "invalid", result, [
            "current_context_invalid"
        ]);
    }
    const mismatched = [
        "jobId",
        "attemptId",
        "checkId"
    ].filter((key)=>record[key] !== context[key]);
    if (mismatched.length) return view(record, "invalid", result, mismatched.map((key)=>`${key}_mismatch`));
    const reasons = [];
    for (const key of originKeys)if (record.origin[key] !== currentOrigin[key]) reasons.push(`${key}_changed`);
    if (reasons.length) return view(record, "stale", result, reasons);
    const supportsPassed = result === "passed" && execution.processIdentity !== null && !unknownFact && record.layer === context.requiredLayer && context.oraclePassed;
    return view(record, "current", result, [], supportsPassed);
}
export function summarizeEvidence(views) {
    const rows = views.map((item)=>Object.freeze({
            checkId: item.record?.checkId ?? null,
            layer: item.record?.layer ?? null,
            validity: item.validity,
            result: item.result,
            reason: item.record?.result.reason ?? "record_invalid",
            counts: item.counts,
            supportsPassed: item.supportsPassed,
            reasons: item.reasons
        }));
    return Object.freeze({
        total: rows.length,
        current: rows.filter((row)=>row.validity === "current").length,
        stale: rows.filter((row)=>row.validity === "stale").length,
        invalid: rows.filter((row)=>row.validity === "invalid").length,
        failed: rows.filter((row)=>row.result === "failed").length,
        unknown: rows.filter((row)=>row.result === "unknown").length,
        supportsPassed: rows.length > 0 && rows.every((row)=>row.supportsPassed),
        rows: Object.freeze(rows)
    });
}
