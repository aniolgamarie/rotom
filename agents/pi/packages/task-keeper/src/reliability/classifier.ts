import type { FailureCategory, Rule } from "../config.ts";

export interface FailureSignal {
  status?: number;
  code?: string;
  message: string;
  headers?: Record<string, string>;
  resetAt?: number;
  stream: "complete" | "error" | "incomplete";
  responseObserved?: boolean;
  admission?: "retry-after" | "transport-wait" | "context-limit";
  controlRevoked?: boolean;
}
export interface Classification {
  category: FailureCategory; retryAt: number | null; code: string; message: string;
  // Optional only for reading historical records; newly classified errors always carry these facts.
  evidence?: { categorySource: "http-status" | "binding-rule" | "transport-signal" | "admission" | "unclassified";
    ruleIndex: number | null; retryAfterAt: number | null; resetAt: number | null; uncertain: boolean };
}

/** Called only at the native settled boundary. HTTP success alone is not stream completion. */
export function successfulRecoveryTerminal(signal: FailureSignal | null): boolean {
  return signal === null || (signal.stream === "complete" && (signal.status === undefined || signal.status < 400));
}

/** SDKs may embed provider JSON in their terminal error rather than emit HTTP error headers. */
export function terminalError(text: string, response: { status: number; headers: Record<string, string>; errorBody?: string } | null, secrets: string[] = []): FailureSignal {
  const leading = /^\s*(?:Error:\s*)?(\d{3})\b/.exec(text)?.[1];
  const status = leading ? Number(leading) : response?.status;
  let code: string | undefined;
  const detail = response && response.status === status ? response.errorBody : undefined;
  for (const candidate of [text, detail]) {
    if (!candidate) continue;
    const start = candidate.indexOf("{");
    if (start < 0) continue;
    try {
      const body = JSON.parse(candidate.slice(start));
      const value = body?.error?.code ?? body?.code;
      if (typeof value === "string" || (typeof value === "number" && Number.isSafeInteger(value))) {
        code = scrub(String(value), secrets).slice(0, 512); break;
      }
    } catch { /* An incomplete/unknown envelope is diagnostic data, not a fabricated provider code. */ }
  }
  return { message: scrub(detail && !text.includes(detail) ? `${text}\nHTTP error detail: ${detail}` : text, secrets), status, code, headers: response && response.status === status ? response.headers : undefined,
    responseObserved: !!response && response.status === status, stream: "error" };
}

export function scrub(text: string, secrets: string[] = [], maxLength = 4000): string {
  let safe = text;
  for (const secret of secrets) if (secret) safe = safe.split(secret).join("[redacted]");
  return safe.replace(/\b(Bearer\s+)[^\s"',;]+/gi, "$1[redacted]")
    .replace(/(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password)["']?\s*[=:]\s*)("[^"]*"|'[^']*'|[^\s,;]+)/gi, "$1[redacted]")
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "[redacted]")
    .slice(0, maxLength);
}

export function retryAfter(value: string | undefined, now: number, serverDate?: string): number | null {
  if (!value) return null;
  const input = value.trim();
  if (/^\d+$/.test(input)) {
    const at = now + Number(input) * 1000;
    return Number.isSafeInteger(at) ? at : null;
  }
  // Invalid numeric strings are not dates (Date.parse("-1") is unexpectedly valid).
  if (/^[+-]?[\d.]+$/.test(input)) return null;
  const at = Date.parse(input);
  const serverNow = serverDate ? Date.parse(serverDate) : NaN;
  if (Number.isFinite(at) && Number.isFinite(serverNow)) return now + Math.max(0, at - serverNow);
  return Number.isFinite(at) ? Math.max(now, at) : null;
}

export function classify(signal: FailureSignal, rules: Rule[], now: number, secrets: string[] = []): Classification {
  const headers = Object.fromEntries(Object.entries(signal.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
  const retry = retryAfter(headers["retry-after"], now, headers.date);
  const reset = typeof signal.resetAt === "number" && Number.isSafeInteger(signal.resetAt) ? Math.max(now, signal.resetAt) : null;
  const retryAt = retry === null ? reset : reset === null ? retry : Math.max(retry, reset);
  let category: FailureCategory = "other";
  let source: NonNullable<Classification["evidence"]>["categorySource"] = "unclassified", ruleIndex: number | null = null;
  if ([401, 403, 402].includes(signal.status ?? 0)) { category = "auth_billing_policy"; source = "http-status"; }
  else if (signal.admission === "context-limit") { category = "context_contract"; source = "admission"; }
  else if (signal.admission === "retry-after") { category = "frequency_limit"; source = "admission"; }
  else if (signal.admission === "transport-wait") { category = "network_overload"; source = "admission"; }
  else {
    const index = rules.findIndex((r) => (r.code === undefined || r.code === signal.code)
      && (r.messageIncludes === undefined || signal.message.toLowerCase().includes(r.messageIncludes.toLowerCase())));
    if (index >= 0) { category = rules[index].category; source = "binding-rule"; ruleIndex = index; }
    else if (signal.status === 429) { category = "frequency_limit"; source = "http-status"; }
    else if ((signal.status ?? 0) >= 500 || signal.stream === "incomplete") { category = "network_overload"; source = (signal.status ?? 0) >= 500 ? "http-status" : "transport-signal"; }
    else if (signal.status === undefined && /\b(?:ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|Connection error|Connection timed out)\b/i.test(signal.message)) { category = "network_overload"; source = "transport-signal"; }
  }
  return { category, retryAt, code: signal.code === undefined ? (signal.status ? `HTTP_${signal.status}` : "UNKNOWN") : scrub(signal.code, secrets, 512), message: scrub(signal.message, secrets),
    evidence: { categorySource: source, ruleIndex, retryAfterAt: retry, resetAt: reset,
      uncertain: category === "other" || category === "execution_unknown" || (category === "window_quota" && retryAt === null) } };
}

export const isTemporaryQuota = (c: FailureCategory): boolean => ["frequency_limit", "resource_pressure", "window_quota"].includes(c);
