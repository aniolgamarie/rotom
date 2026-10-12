import { createHash } from "node:crypto";
import { canonical, digest, finiteInteger, ContractError } from "../contracts/primitives.mjs";
export function compileContextEvidence(body, maxBytes) {
    finiteInteger(maxBytes, 1, 16 * 1024 * 1024);
    const content = canonical(body), bytes = Buffer.byteLength(content, "utf8");
    if (bytes > maxBytes) throw new ContractError("PACKET_TOO_LARGE", `PACKET_TOO_LARGE: ${bytes} UTF-8 bytes exceed evidence.packetByteBudget=${maxBytes}`);
    return {
        content,
        bytes,
        digest: digest(body)
    };
}
export const INPUT_RECORD_LIMIT = 10000, INPUT_SOURCE_LIMIT = 64 * 1024 * 1024, INPUT_METADATA_LIMIT = 1024 * 1024;
export const inputOrder = (a, b)=>Buffer.compare(Buffer.from(a), Buffer.from(b));
const invalidInput = ()=>{
    throw new ContractError("INPUT_SNAPSHOT_INVALID");
};
export function inputCanonical(value, depth = 0) {
    if (depth > 64) return invalidInput();
    if (value === null || typeof value === "boolean") return JSON.stringify(value);
    if (typeof value === "string") {
        if (Buffer.from(value).toString("utf8") !== value) return invalidInput();
        return JSON.stringify(value);
    }
    if (typeof value === "number") {
        if (!Number.isSafeInteger(value)) return invalidInput();
        return JSON.stringify(value);
    }
    if (!value || typeof value !== "object") return invalidInput();
    const descriptors = Object.getOwnPropertyDescriptors(value);
    if (Object.getOwnPropertySymbols(value).length || Object.values(descriptors).some((row)=>!Object.hasOwn(row, "value"))) return invalidInput();
    if (Array.isArray(value)) {
        if (Object.getPrototypeOf(value) !== Array.prototype || Object.getOwnPropertyNames(value).length !== value.length + 1 || Object.keys(value).length !== value.length || value.length > INPUT_RECORD_LIMIT) return invalidInput();
        return `[${value.map((row)=>inputCanonical(row, depth + 1)).join(",")}]`;
    }
    if (Object.getPrototypeOf(value) !== Object.prototype || Object.values(descriptors).some((row)=>!row.enumerable)) return invalidInput();
    return `{${Object.keys(value).sort(inputOrder).map((key)=>`${inputCanonical(key)}:${inputCanonical(value[key], depth + 1)}`).join(",")}}`;
}
export function inputDigest(value) {
    const content = inputCanonical(value);
    if (Buffer.byteLength(content) > INPUT_METADATA_LIMIT) return invalidInput();
    return createHash("sha256").update(content).digest("hex");
}
export function inputPath(value) {
    if (typeof value !== "string" || !value || Buffer.byteLength(value) > 4096 || value.startsWith("/") || value.includes("\\") || /[\x00-\x1f\x7f]/.test(value) || value.split("/").some((part)=>[
            "",
            ".",
            ".."
        ].includes(part))) invalidInput();
}
function closedInput(value, fields) {
    inputCanonical(value);
    if (!value || Array.isArray(value) || Object.keys(value).sort(inputOrder).join() !== [
        ...fields
    ].sort(inputOrder).join()) invalidInput();
}
const hashInput = (v)=>{
    if (typeof v !== "string" || !/^[a-f0-9]{64}$/.test(v)) invalidInput();
};
const textInput = (v)=>{
    if (typeof v !== "string" || !v || v.length > 4096 || /[\x00-\x1f\x7f]/.test(v)) invalidInput();
};
function sortedInput(rows, key) {
    if (!Array.isArray(rows) || rows.length > INPUT_RECORD_LIMIT) invalidInput();
    const keys = rows.map(key);
    if (new Set(keys).size !== keys.length || keys.some((v, i)=>i > 0 && inputOrder(keys[i - 1], v) >= 0)) invalidInput();
}
export function validateSemanticSource(value) {
    closedInput(value, [
        "schema_version",
        "workspace_identity",
        "scope",
        "files",
        "sensitive_inputs"
    ]);
    if (value.schema_version !== 1) invalidInput();
    hashInput(value.workspace_identity);
    const scope = value.scope;
    closedInput(scope, [
        "relative_roots",
        "explicit_inputs",
        "artifact_exclusions",
        "outside_exclusions"
    ]);
    if (inputCanonical(scope.relative_roots) !== '["."]') invalidInput();
    sortedInput(scope.explicit_inputs, (v)=>{
        inputPath(v);
        return v;
    });
    sortedInput(scope.artifact_exclusions, (row)=>{
        closedInput(row, [
            "relative_path",
            "kind"
        ]);
        inputPath(row.relative_path);
        if (![
            "file",
            "directory"
        ].includes(row.kind)) invalidInput();
        return row.relative_path;
    });
    sortedInput(scope.outside_exclusions, (row)=>{
        closedInput(row, [
            "root_ref",
            "category"
        ]);
        textInput(row.root_ref);
        if (![
            "managed-artifact",
            "protected-root"
        ].includes(row.category)) invalidInput();
        return row.root_ref;
    });
    sortedInput(value.files, (row)=>{
        closedInput(row, [
            "relative_path",
            "kind",
            ...row.kind === "file" ? [
                "sha256",
                "executable"
            ] : row.kind === "symlink" ? [
                "target"
            ] : []
        ]);
        inputPath(row.relative_path);
        if (row.kind === "file") {
            hashInput(row.sha256);
            if (!Number.isInteger(row.executable) || row.executable < 0 || row.executable > 511) invalidInput();
        } else if (row.kind === "symlink") inputPath(row.target);
        else if (row.kind !== "missing") invalidInput();
        return row.relative_path;
    });
    sortedInput(value.sensitive_inputs, (row)=>{
        closedInput(row, [
            "reference",
            "category",
            "owner",
            "provider",
            "actor",
            "state"
        ]);
        textInput(row.reference);
        if (row.reference.startsWith("/") || ![
            "credential-file",
            "protected-file",
            "credential-environment"
        ].includes(row.category) || ![
            "source",
            "candidate"
        ].includes(row.actor) || ![
            "present",
            "missing",
            "unreadable"
        ].includes(row.state)) invalidInput();
        for (const k of [
            "owner",
            "provider"
        ])if (row[k] !== null) textInput(row[k]);
        return row.actor + ":" + row.reference;
    });
    if (value.files.length + value.sensitive_inputs.length + scope.explicit_inputs.length + scope.artifact_exclusions.length + scope.outside_exclusions.length > INPUT_RECORD_LIMIT) invalidInput();
    for (const row of value.files)if (row.kind === "symlink" && !value.files.some((v)=>v.relative_path === row.target && v.kind === "file")) invalidInput();
    inputDigest(value);
    return structuredClone(value);
}
export const identityFields = [
    "config_identity",
    "effective_config_digest",
    "host_manifest_identity",
    "policy_digest",
    "project_constraints_digest",
    "resources_digest",
    "taskkeeper_policy_digest",
    "runtime_identity",
    "lock_identity",
    "slice_identity",
    "taskkeeper_runtime_identity",
    "capability_provider_digest",
    "model_routes",
    "checker_contracts",
    "local_acceptance_digest",
    "environment"
];
export function compileInputSnapshot(source, identities) {
    const fixedSource = validateSemanticSource(source);
    closedInput(identities, identityFields);
    for (const key of identityFields.filter((k)=>![
            "model_routes",
            "checker_contracts",
            "environment"
        ].includes(k)))hashInput(identities[key]);
    sortedInput(identities.checker_contracts, (row)=>{
        closedInput(row, [
            "check_id",
            "contract_digest"
        ]);
        textInput(row.check_id);
        hashInput(row.contract_digest);
        return row.check_id;
    });
    sortedInput(identities.model_routes, (row)=>{
        closedInput(row, [
            "role_id",
            "provider_id",
            "model_id",
            "public_configuration_digest",
            "auth"
        ]);
        for (const k of [
            "role_id",
            "provider_id",
            "model_id"
        ])textInput(row[k]);
        hashInput(row.public_configuration_digest);
        closedInput(row.auth, [
            "kind",
            "owner",
            "credential_ref"
        ]);
        if (![
            "api-key",
            "oauth"
        ].includes(row.auth.kind)) invalidInput();
        textInput(row.auth.owner);
        if (row.auth.credential_ref !== null && (typeof row.auth.credential_ref !== "string" || !/^secret:[A-Za-z0-9_.:-]+$/.test(row.auth.credential_ref))) invalidInput();
        return row.role_id;
    });
    const env = identities.environment;
    closedInput(env, [
        "platform",
        "architecture",
        "node_version",
        "sdk_version",
        "declared_nonsecret_variables"
    ]);
    for (const key of [
        "platform",
        "architecture",
        "node_version",
        "sdk_version"
    ])textInput(env[key]);
    if (inputCanonical(env.declared_nonsecret_variables) !== '[{"name":"LANG","value":"C.UTF-8"}]') invalidInput();
    const body = {
        schema_version: 1,
        source: fixedSource,
        identities: structuredClone(identities)
    };
    const result = {
        ...body,
        digest: inputDigest(body)
    };
    if (Buffer.byteLength(inputCanonical(result)) > INPUT_METADATA_LIMIT) invalidInput();
    return result;
}
