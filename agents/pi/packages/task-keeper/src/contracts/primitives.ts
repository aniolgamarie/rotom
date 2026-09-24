import { createHash, randomUUID } from "node:crypto";

export class ContractError extends Error {
  readonly code: string;
  constructor(code: string, message: string = code) {
    super(message);
    this.name = "ContractError";
    this.code = code;
  }
}

/** Stable JSON rejects values that JSON would silently coerce, omit or lose. */
export function canonical(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  throw new ContractError("INVALID_JSON_VALUE");
}

export const digest = (value: unknown): string => createHash("sha256").update(canonical(value)).digest("hex");
export const newId = (prefix: string): string => `${prefix}-${randomUUID()}`;

export function identifier(value: unknown, label = "identity"): asserts value is string {
  if (typeof value !== "string" || !/^[a-zA-Z0-9_.:-]{1,200}$/.test(value)) throw new ContractError("INVALID_ID", label);
}

export function finiteInteger(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max) {
    throw new ContractError("INVALID_INTEGER");
  }
}

export function object(value: unknown, allowed?: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.getPrototypeOf(value) !== Object.prototype) {
    throw new ContractError("INVALID_OBJECT");
  }
  const result = value as Record<string, unknown>;
  if (allowed && Object.keys(result).some((key) => !allowed.includes(key))) throw new ContractError("UNKNOWN_FIELD");
  return result;
}

export interface Clock {
  now(): number;
  monotonic(): number;
  schedule(delayMs: number, callback: () => void): () => void;
}

export const systemClock: Clock = {
  now: () => Date.now(),
  monotonic: () => performance.now(),
  schedule(delayMs, callback) {
    finiteInteger(delayMs, 0, 2_147_483_647);
    const timer = setTimeout(callback, delayMs);
    timer.unref();
    return () => clearTimeout(timer);
  },
};
