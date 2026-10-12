import { createHash, randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { privateBytes, privateFile } from "./private-files.mjs";
import { canonical, digest, reject } from "./managed-types.mjs";
async function runLegacyAuxiliary({ runtime, pi, context, program, payload, cwd, taskId, signal, onDispatch, timeoutMs = 120000, pause = (milliseconds)=>new Promise((resolve)=>setTimeout(resolve, milliseconds)), now = ()=>Date.now() }) {
    const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
    if (!entry?.manager || ![
        "workspace",
        "check"
    ].includes(program)) reject("CAPABILITY_MISSING", 5);
    const supervisor = runtime.supervisor, manager = entry.manager;
    const planned = await supervisor.call("workspace_identity", {
        path: cwd
    });
    const snapshot = program === "workspace" && payload.operation === "create" ? {
        snapshot_digest: null
    } : await supervisor.call("workspace_snapshot", {
        path: cwd
    });
    const execution_id = "aux-" + randomUUID();
    const allocated = await supervisor.call("allocate", {
        kind: program === "check" ? "check" : "external",
        execution_id,
        task_id: taskId,
        attempt_id: execution_id,
        lock_identity: runtime.installed.lock_identity,
        slice_identity: runtime.installed.slice_identity,
        policy_digest: digest(runtime.manifest.permission_policy),
        candidate_digest: snapshot.snapshot_digest,
        planned_workspaces: [
            planned
        ]
    });
    let result, canceled = false, timedOut = false, started = false, failureSettled = false, resolveResult, rejectResult;
    const outcome = new Promise((resolve, reject)=>{
        resolveResult = resolve;
        rejectResult = reject;
    });
    const stateRoot = dirname(dirname(dirname(supervisor.options.endpoint)));
    const stop = async ()=>{
        canceled = true;
        const current = await supervisor.call("inspect", {
            lease_id: allocated.lease_id
        });
        await supervisor.call(current.state === "allocating" ? "abort_allocation" : "cancel", {
            lease_id: allocated.lease_id
        });
        const after = await supervisor.call("inspect", {
            lease_id: allocated.lease_id
        });
        if (!after.protected) {
            if (!started) resolveResult({
                stdout: "",
                stderr: "",
                truncated: false,
                exitCode: null,
                timedOut,
                cancelled: true,
                terminationConfirmed: true,
                started: false,
                lease_id: allocated.lease_id,
                process_identity: null,
                workspace_result: null
            });
            return {
                response_text: "",
                terminal_status: "canceled",
                termination_confirmed: true,
                external_work_empty: true
            };
        }
        return undefined;
    };
    const executor = {
        kind: "external",
        manager_run_id: execution_id,
        cancel: async ()=>{
            try {
                return await stop();
            } catch (error) {
                rejectResult(error);
                throw error;
            }
        },
        async execute () {
            if (signal?.aborted) return stop();
            onDispatch?.();
            const launched = await supervisor.call("start", {
                lease_id: allocated.lease_id,
                program,
                payload
            });
            started = launched.state === "running";
            if (!started) reject("START_UNKNOWN", 4);
            const deadline = now() + timeoutMs;
            for(;;){
                const status = await supervisor.call("inspect", {
                    lease_id: allocated.lease_id
                });
                if (!status.protected) break;
                if (now() >= deadline && !timedOut) {
                    timedOut = true;
                    await stop();
                }
                if (now() > deadline + 10000) reject("TERMINATION_UNKNOWN", 4);
                await pause(250);
            }
            const directory = join(stateRoot, "activity/outputs", allocated.lease_id);
            const capture = JSON.parse(privateFile(join(directory, "capture.json")));
            const exited = JSON.parse(privateFile(join(stateRoot, "activity/exits", allocated.lease_id + ".json")));
            const proof = await supervisor.call("reconcile", {
                lease_id: allocated.lease_id
            });
            if (capture.complete !== true || exited.lease_id !== allocated.lease_id || proof.lease_id !== allocated.lease_id || proof.protected || proof.termination_evidence?.verified !== true || canonical(proof.process_identity) !== canonical(exited.process_identity)) reject("EVIDENCE_MISSING", 5);
            const stdout = privateBytes(join(directory, "stdout")), stderr = privateBytes(join(directory, "stderr"));
            for (const [name, text] of [
                [
                    "stdout",
                    stdout
                ],
                [
                    "stderr",
                    stderr
                ]
            ]){
                if (createHash("sha256").update(text).digest("hex") !== capture.streams[name].sha256) reject("EVIDENCE_IDENTITY", 4);
            }
            result = {
                stdout: stdout.toString("utf8"),
                stderr: stderr.toString("utf8"),
                truncated: capture.truncated,
                exitCode: exited.exit_code,
                timedOut,
                cancelled: canceled && !timedOut,
                terminationConfirmed: true,
                started,
                lease_id: allocated.lease_id,
                process_identity: exited.process_identity,
                workspace_result: program === "workspace" && exited.exit_code === 0 ? JSON.parse(privateFile(join(stateRoot, "activity/workspace-results", allocated.lease_id + ".json"))) : null
            };
            resolveResult(result);
            return {
                response_text: "Auxiliary execution observed",
                terminal_status: exited.exit_code === 0 && !canceled ? "completed" : "failed",
                termination_confirmed: true,
                external_work_empty: true
            };
        }
    };
    const execute = executor.execute;
    executor.execute = async ()=>{
        try {
            return await execute();
        } catch (error) {
            try {
                const observed = await supervisor.call("inspect", {
                    lease_id: allocated.lease_id
                });
                if (observed.state === "allocating") await supervisor.call("abort_allocation", {
                    lease_id: allocated.lease_id
                });
                const proof = await supervisor.call("reconcile", {
                    lease_id: allocated.lease_id
                });
                if (proof.lease_id === allocated.lease_id && !proof.protected && proof.termination_evidence?.verified) {
                    failureSettled = true;
                    return {
                        response_text: "",
                        terminal_status: "failed",
                        termination_confirmed: true,
                        external_work_empty: true
                    };
                }
            } finally{
                rejectResult(error);
            }
            throw error;
        }
    };
    let id;
    try {
        id = manager.spawnWithExecutor(pi ?? entry.pi, context ?? entry.getContext(), "agentcfg-" + program, "Trusted " + program, executor, {
            description: program,
            cwd,
            isBackground: true
        });
    } catch (error) {
        await supervisor.call("abort_allocation", {
            lease_id: allocated.lease_id
        });
        throw error;
    }
    const cancel = ()=>{
        manager.abort(id);
    };
    signal?.addEventListener("abort", cancel, {
        once: true
    });
    try {
        if (signal?.aborted) cancel();
        const value = await outcome;
        await manager.getRecord(id).promise;
        manager.consumeControlled(id);
        return value;
    } finally{
        signal?.removeEventListener("abort", cancel);
        if (failureSettled && manager.getRecord(id)) {
            await manager.getRecord(id).promise;
            manager.consumeControlled(id);
            manager.removeConsumedControlled(id);
        }
    }
}
import { verifyCommandOutput } from "./shell-operation-executor.mjs";
import { captureOperationInput } from "./private-operation-input.mjs";
import { isAbsolute, resolve, relative, sep } from "node:path";
const auxiliaryId = (value)=>typeof value === "string" && /^[A-Za-z0-9_-]{1,200}$/.test(value);
const auxiliaryPath = (value)=>typeof value === "string" && isAbsolute(value) && resolve(value) === value && !/[\u0000-\u001f\u007f]/.test(value);
const auxiliaryFail = (code, exit = 4)=>reject(code, exit);
export async function runAuxiliary(options) {
    const profile = options?.runtime?.manifest?.profile_id;
    if (profile === "pi-base") auxiliaryFail("CAPABILITY_MISSING", 5);
    if (profile !== "pi-full") return runLegacyAuxiliary(options);
    return runModernAuxiliary(options);
}
async function runModernAuxiliary({ runtime, program, payload, cwd, taskId, signal, onDispatch, timeoutMs = 120000, pause = (milliseconds)=>new Promise((resolve)=>setTimeout(resolve, milliseconds)), now = ()=>Date.now() }) {
    const startedAt = now(), deadline = startedAt + timeoutMs;
    const manifest = runtime?.manifest, installed = runtime?.installed, supervisor = runtime?.supervisor;
    if (installed?.schema_version !== 2 || installed.profile_id !== "pi-full" || !manifest?.plugins?.includes("task-keeper") || manifest.plugin_capabilities?.["task-keeper"]?.capability_id !== "task-workflow" || manifest.options?.task_keeper?.enabled !== true || installed.resources?.extensions?.filter((row)=>row.capability_id === "task-workflow").length !== 1 || typeof supervisor?.call !== "function" || !auxiliaryPath(supervisor.options?.endpoint) || !supervisor.options.endpoint.endsWith("/activity/control/control.json") || ![
        "workspace",
        "check"
    ].includes(program) || !auxiliaryPath(cwd) || !auxiliaryId(taskId) || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 86400000 || signal !== undefined && !(signal instanceof AbortSignal) || onDispatch !== undefined && typeof onDispatch !== "function") auxiliaryFail("CAPABILITY_MISSING", 5);
    const fixed = captureOperationInput(payload).value;
    const allowed = program === "workspace" ? [
        "operation",
        "cwd",
        "stateRoot",
        "jobId",
        "baselineTree",
        "extraInputs",
        "timeoutMs"
    ] : [
        "check_id",
        "cwd",
        "task_id",
        "contract_digest"
    ];
    if (!fixed || Object.keys(fixed).some((key)=>!allowed.includes(key)) || fixed.cwd !== cwd || program === "workspace" && (![
        "create",
        "snapshot"
    ].includes(fixed.operation) || fixed.jobId !== taskId || fixed.stateRoot !== join(runtime.instanceRoot, "pi-home/task-keeper")) || program === "check" && (fixed.task_id !== taskId || typeof fixed.contract_digest !== "string" || !/^[a-f0-9]{64}$/.test(fixed.contract_digest) || !manifest.options.task_keeper.check_ids?.includes(fixed.check_id)) || typeof installed.lock_identity !== "string" || typeof installed.slice_identity !== "string") auxiliaryFail("AUXILIARY_INPUT_INVALID", 2);
    const inside = (root, path)=>{
        const tail = relative(root, path);
        return !isAbsolute(tail) && tail !== ".." && !tail.startsWith(".." + sep);
    };
    const projectId = manifest.options.task_keeper.project_root;
    const project = manifest.options.paths?.roots?.[projectId];
    const candidate = join(runtime.instanceRoot, "pi-home/task-keeper/worktrees", taskId);
    const binding = program === "check" ? manifest.options.checks?.[fixed.check_id] : null;
    if (!project || project.purpose !== "project" || !auxiliaryPath(project.path) || program === "workspace" && !inside(fixed.operation === "create" ? project.path : candidate, cwd) || program === "check" && (!inside(candidate, cwd) || binding?.project_root !== projectId)) auxiliaryFail("AUXILIARY_INPUT_INVALID", 2);
    const stateRoot = dirname(dirname(dirname(supervisor.options.endpoint)));
    let lease, generation, identity, execution, markSent = false, startAttempted = false, stopping, stopSent = false, terminal = false;
    const unknown = ()=>auxiliaryFail("TERMINATION_UNKNOWN");
    const request = async (method, args, limit = 5000, cancelable = false)=>{
        let timer, abort;
        try {
            return await Promise.race([
                Promise.resolve().then(()=>supervisor.call(method, args)),
                new Promise((_, fail)=>{
                    timer = setTimeout(()=>fail(Error("AUXILIARY_REPLY_TIMEOUT")), Math.max(1, limit));
                    if (cancelable && signal) {
                        abort = ()=>fail(Error("AUXILIARY_CANCELED"));
                        signal.addEventListener("abort", abort, {
                            once: true
                        });
                        if (signal.aborted) abort();
                    }
                })
            ]);
        } finally{
            clearTimeout(timer);
            if (abort) signal.removeEventListener("abort", abort);
        }
    };
    const observed = (row)=>{
        if (!row || row.lease_id !== lease || row.attempt_id !== execution || row.task_id !== taskId || typeof row.spawn_committed !== "boolean" || row.grant_generation !== generation && !(stopSent && row.grant_generation === generation + 1 && [
            "cancel_requested",
            "reclaimed"
        ].includes(row.state))) unknown();
        if (row.process_identity != null) {
            if (identity === undefined) identity = structuredClone(row.process_identity);
            else if (canonical(identity) !== canonical(row.process_identity)) unknown();
        }
        return row;
    };
    const proof = async ()=>{
        const row = observed(await request("reconcile", {
            lease_id: lease
        }));
        if (row.protected !== false) return null;
        const evidence = row.termination_evidence;
        if (!evidence?.verified || evidence.execution_lease_id !== lease || evidence.grant_generation !== row.grant_generation || typeof evidence.allocation_journal_digest !== "string" || !/^[a-f0-9]{64}$/.test(evidence.allocation_journal_digest) || canonical(evidence.external_work_ids) !== canonical(Object.keys(row.external_status)) || canonical(evidence.process_identities) !== canonical(row.process_identity ? [
            row.process_identity
        ] : []) || evidence.evidence_digest !== digest(Object.fromEntries(Object.entries(evidence).filter(([key])=>key !== "evidence_digest"))) || !(row.state === "reclaimed" && evidence.kind === "terminated" || row.state === "failed" && row.spawn_committed === false && evidence.kind === "never-started")) unknown();
        terminal = true;
        return row;
    };
    const stop = ()=>stopping ??= (async ()=>{
            const row = observed(await request("inspect", {
                lease_id: lease
            }));
            if (!row.protected && await proof()) return;
            const allocating = row.state === "allocating" && row.spawn_committed === false;
            stopSent = !allocating;
            try {
                await request(allocating ? "abort_allocation" : "cancel", {
                    lease_id: lease
                });
            } catch  {}
            const end = now() + 5000;
            for(let polls = 0; polls < 201 && now() < end; polls++){
                if (await proof()) return;
                await pause(25);
            }
            unknown();
        })();
    const cancel = ()=>{
        if (lease) void stop().catch(()=>{});
    };
    signal?.addEventListener("abort", cancel, {
        once: true
    });
    try {
        if (signal?.aborted || now() >= deadline) auxiliaryFail("AUXILIARY_CANCELED");
        const planned = await request("workspace_identity", {
            path: cwd
        });
        const snapshot = program === "workspace" && fixed.operation === "create" ? {
            snapshot_digest: null
        } : await request("workspace_snapshot", {
            path: cwd
        });
        if (signal?.aborted || now() >= deadline) auxiliaryFail("AUXILIARY_CANCELED");
        if (onDispatch) await onDispatch();
        markSent = true;
        if (signal?.aborted || now() >= deadline) unknown();
        execution = "aux-" + randomUUID();
        const allocation = await request("allocate", {
            kind: program === "check" ? "check" : "external",
            execution_id: execution,
            task_id: taskId,
            attempt_id: execution,
            lock_identity: installed.lock_identity,
            slice_identity: installed.slice_identity,
            policy_digest: digest(manifest.permission_policy),
            candidate_digest: snapshot.snapshot_digest,
            planned_workspaces: [
                planned
            ]
        });
        if (!auxiliaryId(allocation?.lease_id) || allocation.allocation_id !== allocation.lease_id || allocation.state !== "allocating" || !Number.isSafeInteger(allocation.grant_generation) || allocation.grant_generation < 1) unknown();
        lease = allocation.lease_id;
        generation = allocation.grant_generation;
        if (signal?.aborted) {
            await stop();
            auxiliaryFail("AUXILIARY_CANCELED");
        }
        startAttempted = true;
        try {
            const reply = await request("start", {
                lease_id: lease,
                program,
                payload: fixed
            }, Math.min(30000, deadline - now()), true);
            if (reply?.lease_id !== lease || reply.attempt_id !== execution || reply.state !== "running") unknown();
        } catch  {
            if (signal?.aborted) {
                await stop();
                auxiliaryFail("AUXILIARY_CANCELED");
            }
            observed(await request("inspect", {
                lease_id: lease
            }));
        }
        for(let polls = 0; polls < Math.ceil(timeoutMs / 25) + 1 && now() < deadline; polls++){
            if (signal?.aborted) {
                await stop();
                auxiliaryFail("AUXILIARY_CANCELED");
            }
            const ended = await proof();
            if (signal?.aborted) {
                await stop();
                auxiliaryFail("AUXILIARY_CANCELED");
            }
            if (now() >= deadline) {
                await stop();
                auxiliaryFail("AUXILIARY_TIMEOUT");
            }
            if (ended) {
                const result = verifyCommandOutput(stateRoot, lease, ended);
                let workspace_result = null;
                if (program === "workspace" && result.exitCode === 0) {
                    const row = captureOperationInput(JSON.parse(privateFile(join(stateRoot, "activity/workspace-results", lease + ".json")))).value;
                    if (!row || !row.snapshot || typeof row.snapshot.id !== "string" || fixed.operation === "create" && (!row.baseline || !auxiliaryPath(row.path) || !auxiliaryPath(row.cwd))) auxiliaryFail("EVIDENCE_IDENTITY");
                    workspace_result = row;
                }
                return {
                    ...result,
                    timedOut: false,
                    cancelled: false,
                    started: true,
                    lease_id: lease,
                    process_identity: ended.process_identity,
                    workspace_result
                };
            }
            await pause(25);
        }
        await stop();
        auxiliaryFail("AUXILIARY_TIMEOUT");
    } catch (error) {
        if (lease && !terminal) {
            try {
                await stop();
            } catch  {
                unknown();
            }
        }
        if (markSent && !lease || startAttempted && !terminal) unknown();
        if ([
            "AUXILIARY_CANCELED",
            "AUXILIARY_TIMEOUT",
            "EVIDENCE_IDENTITY",
            "ORDINARY_OPERATION_EVIDENCE"
        ].includes(error?.code)) throw error;
        auxiliaryFail("AUXILIARY_CONTROL_UNAVAILABLE", 5);
    } finally{
        signal?.removeEventListener("abort", cancel);
    }
}
