import { dirname, isAbsolute, join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { privateFile } from "./private-files.mjs";
import { canonical, reject } from "./managed-types.mjs";
export async function executeFileOperation({ supervisor, instanceRoot, ticket, content, expectedDigest, signal, pause = (milliseconds)=>new Promise((resolve)=>setTimeout(resolve, milliseconds)), clock = ()=>performance.now() }) {
    const id = (value)=>typeof value === "string" && /^[A-Za-z0-9_-]{1,200}$/.test(value);
    const absolute = (value)=>typeof value === "string" && isAbsolute(value) && resolve(value) === value && !/[\u0000-\u001f\u007f]/.test(value);
    const endpoint = supervisor?.options?.endpoint;
    if (ticket?.kind !== "file" || ticket.write !== true || ticket.state !== "consumed" || !id(ticket.lease_id) || !id(ticket.operation_id) || ![
        "write",
        "edit",
        "rename"
    ].includes(ticket.tool_name) || !absolute(instanceRoot) || !absolute(endpoint) || !endpoint.endsWith("/activity/control/control.json")) reject("ORDINARY_FILE_TICKET", 4);
    const stateRoot = dirname(dirname(dirname(endpoint)));
    ticket.state = "executing";
    const lease = ticket.lease_id;
    let terminal = false;
    const request = async (method, params)=>{
        let timer;
        try {
            return await Promise.race([
                Promise.resolve().then(()=>supervisor.call(method, params)),
                new Promise((_resolve, fail)=>{
                    timer = setTimeout(()=>fail(new Error("SUPERVISOR_REPLY_TIMEOUT")), 5000);
                })
            ]);
        } finally{
            clearTimeout(timer);
        }
    };
    const call = (method, params = {})=>request(method, {
            lease_id: lease,
            ...params
        });
    const unknown = ()=>{
        ticket.state = "unknown";
        reject("TERMINATION_UNKNOWN", 4);
    };
    const proof = async ()=>{
        if (ticket.state === "unknown") unknown();
        const observed = await call("reconcile");
        if (observed?.lease_id !== lease) unknown();
        if (observed.protected === false && observed.termination_evidence?.verified === true) {
            terminal = true;
            ticket.state = "terminated";
            return observed;
        }
        return null;
    };
    const cancel = async (reason)=>{
        try {
            await call("cancel");
        } catch  {}
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
    try {
        if (signal?.aborted) return await cancel("ORDINARY_OPERATION_CANCELED");
        if (ticket.tool_name !== "rename") await request("ordinary_stage_write", {
            operation_id: ticket.operation_id,
            content,
            expected_digest: expectedDigest
        });
        if (signal?.aborted) return await cancel("ORDINARY_OPERATION_CANCELED");
        try {
            await call("start", {
                program: "file-operation",
                payload: {
                    operation_id: ticket.operation_id
                }
            });
        } catch  {
            try {
                const observed = await call("inspect");
                if (observed?.lease_id !== lease) unknown();
            } catch (error) {
                if (ticket.state === "unknown") throw error;
            }
        }
        const deadline = clock() + 30000;
        for(let polls = 0; polls < 1201 && clock() < deadline; polls++){
            if (signal?.aborted) return await cancel("ORDINARY_OPERATION_CANCELED");
            let ended;
            try {
                ended = await proof();
            } catch  {
                if (ticket.state === "unknown") unknown();
            }
            if (ended) {
                let exit, result;
                try {
                    exit = JSON.parse(privateFile(join(stateRoot, "activity/exits", lease + ".json")));
                    result = JSON.parse(privateFile(join(stateRoot, "activity/ordinary-results", ticket.operation_id + ".json")));
                } catch  {
                    reject("ORDINARY_OPERATION_EVIDENCE", 5);
                }
                if (exit.lease_id !== lease || !exit.process_identity || !ended.process_identity || canonical(exit.process_identity) !== canonical(ended.process_identity) || exit.exit_code !== 0 || result.schema_version !== 1 || result.lease_id !== lease || result.operation_id !== ticket.operation_id || result.result === null || typeof result.result !== "object" || Array.isArray(result.result)) reject("ORDINARY_OPERATION_EVIDENCE", 5);
                return result.result;
            }
            await pause(25);
        }
        return await cancel("ORDINARY_OPERATION_TIMEOUT");
    } catch (error) {
        if (terminal || ticket.state === "unknown") throw error;
        try {
            await cancel("ORDINARY_OPERATION_FAILED");
        } catch (settled) {
            if (!terminal) throw settled;
        }
        throw error;
    }
}
