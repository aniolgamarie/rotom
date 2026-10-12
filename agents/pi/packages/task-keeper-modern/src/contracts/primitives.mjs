import { createHash, randomUUID } from "node:crypto";
export class ContractError extends Error {
    code;
    constructor(code, message = code){
        super(message);
        this.name = "ContractError";
        this.code = code;
    }
}
export function canonical(value) {
    if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
    if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype) {
        return `{${Object.keys(value).sort().map((key)=>`${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
    }
    throw new ContractError("INVALID_JSON_VALUE");
}
export const digest = (value)=>createHash("sha256").update(canonical(value)).digest("hex");
export const newId = (prefix)=>`${prefix}-${randomUUID()}`;
export function identifier(value, label = "identity") {
    if (typeof value !== "string" || !/^[a-zA-Z0-9_.:-]{1,200}$/.test(value)) throw new ContractError("INVALID_ID", label);
}
export function finiteInteger(value, min = 0, max = Number.MAX_SAFE_INTEGER) {
    if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max) {
        throw new ContractError("INVALID_INTEGER");
    }
}
export function object(value, allowed) {
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.getPrototypeOf(value) !== Object.prototype) {
        throw new ContractError("INVALID_OBJECT");
    }
    const result = value;
    if (allowed && Object.keys(result).some((key)=>!allowed.includes(key))) throw new ContractError("UNKNOWN_FIELD");
    return result;
}
export const systemClock = {
    now: ()=>Date.now(),
    monotonic: ()=>performance.now(),
    schedule (delayMs, callback) {
        finiteInteger(delayMs, 0, 2_147_483_647);
        const timer = setTimeout(callback, delayMs);
        timer.unref();
        return ()=>clearTimeout(timer);
    }
};
