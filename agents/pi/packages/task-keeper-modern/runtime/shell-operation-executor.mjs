import { createHash } from "node:crypto";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { privateBytes } from "./private-files.mjs";
import { canonical, closed, reject, sha } from "./managed-types.mjs";
const retainedLimit = 1024 * 1024, previewLimit = 8192;
const id = (value)=>typeof value === "string" && /^[A-Za-z0-9_-]{1,200}$/.test(value);
const absolute = (value)=>typeof value === "string" && isAbsolute(value) && resolve(value) === value && !/[\u0000-\u001f\u007f]/.test(value);
export function verifyCommandOutput(root, lease, proof, streamed = null, streamComplete = true) {
    try {
        if (typeof streamComplete !== "boolean") throw Error();
        const read = (path)=>JSON.parse(privateBytes(path, 65536).toString("utf8"));
        const exit = read(join(root, "activity/exits", lease + ".json"));
        closed(exit, [
            "schema_version",
            "lease_id",
            "process_identity",
            "exit_code"
        ]);
        if (exit.schema_version !== 1 || exit.lease_id !== lease || !exit.process_identity || !proof.process_identity || canonical(exit.process_identity) !== canonical(proof.process_identity) || !Number.isInteger(exit.exit_code) || Math.abs(exit.exit_code) > 255) throw Error();
        const directory = join(root, "activity/outputs", lease), capture = read(join(directory, "capture.json"));
        closed(capture, [
            "schema_version",
            "complete",
            "truncated",
            "streams"
        ]);
        closed(capture.streams, [
            "stdout",
            "stderr"
        ]);
        if (capture.schema_version !== 1 || capture.complete !== true || typeof capture.truncated !== "boolean") throw Error();
        const result = {};
        for (const name of [
            "stdout",
            "stderr"
        ]){
            const row = capture.streams[name];
            closed(row, [
                "path",
                "sha256",
                "bytes",
                "truncated",
                "failed"
            ]);
            if (row.path !== name || !sha(row.sha256) || !Number.isSafeInteger(row.bytes) || row.bytes < 0 || row.bytes > retainedLimit || typeof row.truncated !== "boolean" || row.failed !== false) throw Error();
            const bytes = privateBytes(join(directory, name), retainedLimit);
            if (bytes.length !== row.bytes || createHash("sha256").update(bytes).digest("hex") !== row.sha256) throw Error();
            if (streamed) {
                const seen = streamed[name];
                if (seen.bytes > row.bytes || streamComplete && (seen.bytes !== row.bytes || seen.overflow !== row.truncated) || seen.overflow && !row.truncated || seen.hash.copy().digest("hex") !== createHash("sha256").update(bytes.subarray(0, seen.bytes)).digest("hex")) throw Error();
            }
            result[name] = bytes.toString("utf8");
        }
        if (capture.truncated !== Object.values(capture.streams).some((row)=>row.truncated)) throw Error();
        return {
            ...result,
            exitCode: exit.exit_code,
            truncated: capture.truncated,
            terminationConfirmed: true
        };
    } catch  {
        reject("ORDINARY_OPERATION_EVIDENCE", 5);
    }
}
export async function executeShellOperation({ supervisor, ticket, signal, onUpdate, pause = (milliseconds)=>new Promise((resolve)=>setTimeout(resolve, milliseconds)), clock = ()=>performance.now() }) {
    const endpoint = supervisor?.options?.endpoint;
    if (typeof supervisor?.call !== "function" || ticket?.kind !== "command" || ticket.tool_name !== "bash" || ticket.state !== "consumed" || !id(ticket.operation_id) || !id(ticket.lease_id) || typeof ticket.write !== "boolean" || !sha(ticket.request_digest) || typeof ticket.command_ref !== "string" || !/^tool:[a-z][a-z0-9_-]{0,63}$/.test(ticket.command_ref) || !Number.isSafeInteger(ticket.timeout_seconds) || ticket.timeout_seconds < 1 || ticket.timeout_seconds > Math.floor(Number.MAX_SAFE_INTEGER / 1000) || !absolute(endpoint) || !endpoint.endsWith("/activity/control/control.json") || !(signal instanceof AbortSignal) || onUpdate !== undefined && typeof onUpdate !== "function") reject("ORDINARY_SHELL_TICKET", 4);
    const lease = ticket.lease_id, operation = ticket.operation_id, timeout = ticket.timeout_seconds * 1000;
    const root = dirname(dirname(dirname(endpoint)));
    ticket.state = "executing";
    let terminal = false, startAttempted = false, cancelAttempted = false, cursor = 0, dropped = false;
    let preview = Buffer.alloc(0), previewTruncated = false;
    const streamed = Object.fromEntries([
        "stdout",
        "stderr"
    ].map((name)=>[
            name,
            {
                bytes: 0,
                overflow: false,
                hash: createHash("sha256")
            }
        ]));
    const previewText = ()=>{
        const encoded = Buffer.from(preview.toString("utf8"));
        let start = Math.max(0, encoded.length - previewLimit);
        previewTruncated ||= start > 0;
        while(start < encoded.length && (encoded[start] & 0xc0) === 0x80)start++;
        return encoded.subarray(start).toString("utf8");
    };
    const request = async (method, args, startDeadline)=>{
        let timer, abort;
        try {
            const limit = startDeadline === undefined ? 5000 : Math.max(1, Math.min(30000, startDeadline - clock()));
            return await Promise.race([
                Promise.resolve().then(()=>supervisor.call(method, args)),
                new Promise((_, fail)=>{
                    timer = setTimeout(()=>fail(Error("SUPERVISOR_REPLY_TIMEOUT")), limit);
                    if (startDeadline !== undefined) {
                        abort = ()=>fail(Error("ORDINARY_OPERATION_CANCELED"));
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
    const call = (method)=>request(method, {
            lease_id: lease
        });
    const unknown = ()=>{
        ticket.state = "unknown";
        reject("TERMINATION_UNKNOWN", 4);
    };
    const proof = async ()=>{
        if (ticket.state === "unknown") unknown();
        const result = await call("reconcile");
        if (result?.lease_id !== lease) unknown();
        if (result.protected === false && result.termination_evidence?.verified === true) {
            terminal = true;
            ticket.state = "terminated";
            return result;
        }
        return null;
    };
    const stop = async (reason)=>{
        if (!cancelAttempted) {
            cancelAttempted = true;
            try {
                if (!startAttempted) {
                    const observed = await call("inspect");
                    if (observed?.lease_id !== lease) unknown();
                    await call(observed.state === "allocating" && observed.spawn_committed === false ? "abort_allocation" : "cancel");
                } else await call("cancel");
            } catch  {
                if (ticket.state === "unknown") unknown();
            }
        }
        const deadline = clock() + 5000;
        for(let polls = 0; polls < 201 && clock() < deadline; polls++){
            try {
                if (await proof()) reject(reason, 4);
            } catch (error) {
                if (terminal || ticket.state === "unknown") throw error;
            }
            await pause(25);
        }
        unknown();
    };
    const output = async ()=>{
        try {
            const result = await request("ordinary_shell_output", {
                operation_id: operation,
                cursor
            });
            closed(result, [
                "events",
                "next_cursor",
                "dropped",
                "has_more",
                "complete"
            ]);
            if (!Array.isArray(result.events) || result.events.length > 4 || !Number.isSafeInteger(result.next_cursor) || result.next_cursor < cursor || [
                "dropped",
                "has_more",
                "complete"
            ].some((key)=>typeof result[key] !== "boolean")) throw Error();
            let previous = cursor;
            for (const row of result.events){
                closed(row, [
                    "seq",
                    "stream",
                    "data_b64"
                ]);
                if (!Number.isSafeInteger(row.seq) || row.seq <= previous || !result.dropped && row.seq !== previous + 1 || ![
                    "stdout",
                    "stderr"
                ].includes(row.stream) || typeof row.data_b64 !== "string" || row.data_b64.length > 87384) throw Error();
                const bytes = Buffer.from(row.data_b64, "base64");
                if (!bytes.length || bytes.length > 65536 || bytes.toString("base64") !== row.data_b64) throw Error();
                previous = row.seq;
                const stream = streamed[row.stream], room = retainedLimit - stream.bytes;
                const retained = bytes.subarray(0, room);
                stream.hash.update(retained);
                stream.bytes += retained.length;
                stream.overflow ||= bytes.length > room;
                const joined = Buffer.concat([
                    preview,
                    bytes
                ]);
                previewTruncated ||= joined.length > previewLimit;
                preview = joined.subarray(Math.max(0, joined.length - previewLimit));
            }
            if (result.next_cursor !== previous || !result.events.length && result.has_more) throw Error();
            dropped ||= result.dropped;
            cursor = result.next_cursor;
            if (result.events.length || result.dropped) {
                const text = previewText();
                onUpdate?.({
                    text,
                    truncated: previewTruncated || dropped,
                    terminationConfirmed: false
                });
            }
            return result;
        } catch  {
            reject("ORDINARY_SHELL_OUTPUT", 5);
        }
    };
    try {
        if (signal.aborted) return await stop("ORDINARY_OPERATION_CANCELED");
        const deadline = clock() + timeout;
        startAttempted = true;
        try {
            const launched = await request("start", {
                lease_id: lease,
                program: "ordinary-shell",
                payload: {
                    operation_id: operation
                }
            }, deadline);
            if (launched?.lease_id !== lease) unknown();
        } catch  {
            if (ticket.state === "unknown") unknown();
        }
        const limit = Math.ceil(timeout / 25) + 1;
        for(let polls = 0; polls < limit && clock() < deadline; polls++){
            if (signal.aborted) return await stop("ORDINARY_OPERATION_CANCELED");
            const live = await output();
            if (clock() >= deadline) return await stop("ORDINARY_OPERATION_TIMEOUT");
            let ended;
            try {
                ended = await proof();
            } catch  {
                if (ticket.state === "unknown") unknown();
            }
            if (signal.aborted) return await stop("ORDINARY_OPERATION_CANCELED");
            if (clock() >= deadline) return await stop("ORDINARY_OPERATION_TIMEOUT");
            if (ended && live.complete) {
                const result = verifyCommandOutput(root, lease, ended, dropped ? null : streamed, !live.has_more);
                const output = previewText();
                return {
                    ...result,
                    output,
                    truncated: result.truncated || dropped || previewTruncated || live.has_more
                };
            }
            await pause(live.has_more ? 0 : 25);
        }
        return await stop("ORDINARY_OPERATION_TIMEOUT");
    } catch (error) {
        if (terminal || ticket.state === "unknown") throw error;
        try {
            await stop("ORDINARY_OPERATION_FAILED");
        } catch (settled) {
            if (!terminal) throw settled;
        }
        if ([
            "ORDINARY_SHELL_OUTPUT",
            "ORDINARY_OPERATION_CANCELED",
            "ORDINARY_OPERATION_TIMEOUT"
        ].includes(error?.message)) throw error;
        reject("ORDINARY_OPERATION_FAILED", 5);
    }
}
